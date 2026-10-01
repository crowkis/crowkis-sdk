"use strict";

// Crowkis in front of a voice agent's model and text-to-speech. Mirrors crowkis/voice.py.
//
// VoiceSession is the voice pipeline: lookups under a hard latency budget, cached
// audio per voice, fillers, barge-in. Every cache decision (what to look up, what
// the model reads, what may be saved) comes from conversation.js, the same policy a
// chat backend uses; the word rules live in rules.js.

const { FILLER, KEPT, LOOKUP, NON_ANSWER, PRIVATE, Conversation } = require("./conversation.js");
const { abstract, fill, isContextDependent, isPersonal } = require("./rules.js");

// A hard deadline: a slow or hung cache must never hold a live call past its budget.
function within(ms, promise) {
  let timer;
  const late = new Promise((resolve) => {
    timer = setTimeout(() => resolve(LATE), ms);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

const LATE = Symbol("late");

class TurnDecision {
  constructor(action, { text = null, audio = null, confidence = 0, reason = "" } = {}) {
    this.action = action;
    this.text = text;
    this.audio = audio;
    this.confidence = confidence;
    this.reason = reason;
    // For a model turn: what the model must read, and whether its answer is shared.
    // null means "the whole call", and then the answer is never shared.
    this.messages = null;
    this.cacheable = false;
  }

  get servedFromCache() {
    return this.action === "serve";
  }

  get servedFromFiller() {
    return this.action === "filler";
  }

  get needsModel() {
    return this.action === "infer";
  }

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
  }
}

class VoiceSession {
  constructor(
    agent,
    {
      voice,
      serveAbove = 0.92,
      minWords = 3,
      synthesise,
      ttl,
      latencyBudgetMs,
      fillers,
      values,
      maxTurns = null,
    } = {}
  ) {
    if (!(serveAbove >= 0 && serveAbove <= 1)) {
      throw new Error(`serveAbove must be in 0..1, got ${serveAbove}`);
    }
    if (latencyBudgetMs !== undefined && latencyBudgetMs !== null && !(latencyBudgetMs > 0)) {
      throw new Error(`latencyBudgetMs must be positive, got ${latencyBudgetMs}`);
    }
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "VoiceSession requires a voice id. Cached audio is only reusable for the " +
          "voice that produced it, and switching voices mid-call is audible"
      );
    }
    this.agent = agent;
    this.voice = voiceId;
    this.serveAbove = serveAbove;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.conversation = new Conversation({ minWords, values, fillers, maxTurns });
    this.served = 0;
    this.inferred = 0;
    this.filled = 0;
    this.refusedShort = 0;
    this.refusedPrivate = 0;
    this.uncacheablePersonal = 0;
    this.overBudget = 0;
    this.bargeIns = 0;
    this.lookupErrors = 0;
    this.learnErrors = 0;
    this.notShareable = 0;
    this.nonAnswers = 0;
    this._plan = null; // the model turn decide() last handed out
  }

  // --- the conversation's state, as before --------------------------------------------------

  get transcript() {
    return this.conversation.transcript;
  }

  get values() {
    return this.conversation.values;
  }

  get minWords() {
    return this.conversation.minWords;
  }

  setValues(values = {}) {
    this.conversation.setValues(values);
  }

  registerFiller(trigger, response) {
    this.conversation.registerFiller(trigger, response);
  }

  registerFillers(pairs = {}) {
    this.conversation.registerFillers(pairs);
  }

  // --- one turn -----------------------------------------------------------------------------

  async decide(callerSaid) {
    const plan = this.conversation.plan(callerSaid);
    const decision = await this._decide(plan);
    this._plan = decision.needsModel ? plan : null;
    if (decision.needsModel) {
      decision.messages = plan.messages;
      decision.cacheable = plan.shareable;
    }
    return decision;
  }

  async _decide(plan) {
    if (plan.reason === "empty") {
      this.refusedShort += 1;
      return new TurnDecision("infer", { reason: "empty transcript" });
    }
    if (plan.action === FILLER) {
      this.filled += 1;
      return new TurnDecision("filler", {
        text: plan.filler,
        audio: await this._voiced(plan.filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
      });
    }
    if (plan.reason === "short") {
      this.refusedShort += 1;
      return new TurnDecision("infer", { reason: "transcript too short to match safely" });
    }
    if (plan.reason === "personal_no_values") {
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the caller asked about their own records and this session has no values " +
          "to fill a shared answer shape with, so nothing can be answered from " +
          "cache without one caller's answer reaching the next",
      });
    }
    if (plan.action !== LOOKUP) {
      // no_prior_turn
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the utterance only has meaning against an earlier turn and this call " +
          "has none, so no cache key can be built for it",
      });
    }

    let hit;
    const started = performance.now();
    try {
      const lookup = this.agent.ask(plan.key, {
        serveAbove: this.serveAbove,
        cheapAbove: Math.min(0.6, this.serveAbove),
        template: plan.template,
        threshold: plan.threshold === null ? undefined : plan.threshold,
      });
      const budgeted = this.latencyBudgetMs !== undefined && this.latencyBudgetMs !== null;
      hit = budgeted ? await within(this.latencyBudgetMs, lookup) : await lookup;
      // Cut off a slow lookup, and refuse one that finished after the budget.
      if (hit === LATE || (budgeted && performance.now() - started > this.latencyBudgetMs)) {
        lookup.catch(() => {});
        this.overBudget += 1;
        this.inferred += 1;
        return new TurnDecision("infer", {
          reason:
            `lookup passed the ${this.latencyBudgetMs}ms voice budget; ` +
            "a late hit is worse than a fast miss",
        });
      }
    } catch (error) {
      // An unreachable or refusing cache means "ask the model", never silence.
      this.lookupErrors += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason: `cache unavailable (${error && error.name}); asking the model`,
      });
    }

    if (hit.route !== "cache") {
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason: hit.confidence > 0
          ? `confidence below the spoken-answer bar of ${this.serveAbove}`
          : "nothing similar is cached yet",
      });
    }

    const answer = this.conversation.served(plan, hit.answer);
    if (answer === null) {
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason:
          "the shared answer shape has a slot this call has no value for; " +
          "speaking a half-filled answer is worse than a model call",
      });
    }

    this.served += 1;
    return new TurnDecision("serve", {
      text: answer,
      audio: await this._voiced(answer, { cacheable: !plan.personal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
  }

  cancel() {
    if (!this.conversation.cancel()) return false;
    this.bargeIns += 1;
    return true;
  }

  // Run one caller turn end to end: cache, or the model, then remember the answer.
  // `llm` is called with exactly the messages Crowkis chose for this turn: the
  // question alone (or with the question before it) when the answer may be shared,
  // the whole call when it may not. `system` is the app's own instructions, the
  // same for every caller, and is put first. The returned decision carries the
  // text to speak, from the cache or from the model.
  async answer(callerSaid, llm, { system = null } = {}) {
    const decision = await this.decide(callerSaid);
    if (!decision.needsModel) return decision;
    decision.text = await llm(this.conversation.modelMessages(this._plan, system));
    await this._recordModelTurn(callerSaid, decision.text);
    return decision;
  }

  // Keep a turn in this call's transcript and never cache it. For a model that
  // holds the whole conversation itself (a realtime speech model): it cannot be
  // given decision.messages, so nothing it says is shared.
  recordPrivateTurn(callerSaid, modelSaid) {
    const plan = this._plan;
    this._plan = null;
    if (this.conversation.keepPrivate(callerSaid, modelSaid) && plan !== null && plan.shareable) {
      this.notShareable += 1;
    }
  }

  // Record the model's answer to the turn decide() last handled, and cache it if
  // allowed. Only an answer written from decision.messages reaches this, so it is
  // shared exactly when decide() said it may be. Never rejects: a refused write
  // (security pipeline, rate limit, cache down) must not end a call.
  // Returns what happened to the answer: saved | template | kept (not shareable) |
  // non_answer | private | refused (write failed) | interrupted | not_saved (empty
  // answer, or a follow-up with nothing before it).
  async _recordModelTurn(callerSaid, modelSaid) {
    let plan = this._plan;
    this._plan = null;
    if (plan === null || plan.said !== callerSaid) plan = this.conversation.unplanned(callerSaid);
    const saving = this.conversation.settle(plan, modelSaid);
    if (saving.outcome === NON_ANSWER) this.nonAnswers += 1;
    else if (saving.outcome === PRIVATE) this.uncacheablePersonal += 1;
    else if (saving.outcome === KEPT) this.notShareable += 1;
    if (!saving.write) return saving.outcome;
    try {
      await this.agent.learn(saving.key, saving.text, { ttl: this.ttl, template: saving.template });
    } catch (error) {
      this.learnErrors += 1;
      return "refused";
    }
    return saving.outcome;
  }

  injections() {
    return this.conversation.transcript.slice();
  }

  stats() {
    const total = this.served + this.inferred + this.filled;
    const pct = (count) => (total ? Math.round((10000 * count) / total) / 100 : 0);
    return {
      turns: total,
      servedFromCache: this.served,
      answeredByFiller: this.filled,
      modelCalls: this.inferred,
      refusedTooShort: this.refusedShort,
      refusedToShareAPrivateAnswer: this.refusedPrivate,
      uncacheablePersonal: this.uncacheablePersonal,
      missedLatencyBudget: this.overBudget,
      bargeIns: this.bargeIns,
      cacheUnavailable: this.lookupErrors,
      failedWrites: this.learnErrors,
      notShareable: this.notShareable,
      nonAnswersNotSaved: this.nonAnswers,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
    };
  }

  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    if (!cacheable) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
    });
  }
}

module.exports = {
  VoiceSession,
  TurnDecision,
  // Re-exported: tests and harnesses read these from voice.js.
  _isPersonal: isPersonal,
  _isContextDependent: isContextDependent,
  _abstract: abstract,
  _fill: fill,
};
