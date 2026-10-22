"use strict";

const { RuleChain } = require("../rules/chain.js");
const { CONTEXT_BOUND_THRESHOLD, normalise } = require("../understanding/wordRules/index.js");
const { CachedAnswer } = require("./cachedAnswer.js");
const { TurnDecision } = require("./decision.js");
const { ModelAnswer } = require("./modelAnswer.js");
const { VoiceTurn } = require("./voiceTurn.js");

/**
 * Template Method: the fixed steps of a voice turn. decide(): open the turn, understand it, the
 * question rules, a filler, the lookup inside the budget, the hit rules, serve. record(): pair the
 * answer with its turn, the save rules, a shared shape for a personal answer, the bounded write.
 * The steps' parts are injected (the rules, the classifier and rewriter, the turn pairing, the
 * lookup, the call as the rules see it); `host` is the session that owns the call's transcript,
 * fillers, audio, counters and the agent the answers are written through.
 */
class TurnCore {
  constructor(host, { rules, call, pairing, cacheLookup, classifier, rewriter }) {
    this._host = host;
    this._rules = rules;
    this._call = call;
    this._pairing = pairing;
    this._cacheLookup = cacheLookup;
    this._classifier = classifier;
    this._rewriter = rewriter;
  }

  async decide(callerSaid) {
    this._pairing.start(this._host.transcript.length);

    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    const reading = this._classifier.classify(text);
    const turn = new VoiceTurn(callerSaid, this._call, reading, this._rewriter.rewrite(text, reading));
    let verdict = this._rules.beforeFiller.firstObjection(turn);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict);

    const filler = this._host._fillers.get(normalise(turn.text));
    if (filler !== undefined) {
      this._host.filled += 1;
      const decision = new TurnDecision("filler", {
        text: filler,
        audio: await this._host._voiced(filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
        rule: "RegisteredFiller",
      });
      decision._audioShareable = true;
      return decision;
    }

    verdict = this._rules.question.firstObjection(turn);

    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict);

    const started = performance.now();
    const { hit, verdict: lookupVerdict } = await this._lookup(turn, started);
    if (lookupVerdict) return this._infer(lookupVerdict);

    const cached = new CachedAnswer(turn, hit, started);
    verdict = this._rules.hit.firstObjection(cached);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict, hit.confidence);

    this._host.served += 1;
    this._host.transcript.push({ role: "user", content: callerSaid });
    this._host.transcript.push({ role: "assistant", content: cached.answer });
    const decision = new TurnDecision("serve", {
      text: cached.answer,
      audio: await this._host._voiced(cached.answer, { cacheable: !turn.isPersonal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
    decision._audioShareable = !turn.isPersonal;
    return decision;
  }

  // The cache's hit for a turn, within the latency budget, or a Verdict when the cache was too
  // slow or could not be reached (the model answers then).
  async _lookup(turn, started) {
    const ask = () => this._host.agent.ask(turn.key, {
      serveAbove: this._host.serveAbove,
      cheapAbove: Math.min(0.6, this._host.serveAbove),
      template: turn.isPersonal,
      threshold: turn.isContextDependent || turn.isShort ? CONTEXT_BOUND_THRESHOLD : undefined,
    });
    return this._cacheLookup.find(ask, started, this._host.latencyBudgetMs);
  }

  // The model answers this turn: `verdict` says which rule decided so, and why.
  _infer(verdict, confidence = 0) {
    this._countVerdict(verdict);
    this._host._ruleCounts.set(verdict.rule, (this._host._ruleCounts.get(verdict.rule) || 0) + 1);
    return new TurnDecision("infer", { confidence, reason: verdict.reason, rule: verdict.rule });
  }

  _countVerdict(verdict) {
    for (const name of verdict.counts) this._host[name] += 1;
  }

  // _record without the per-rule count: the save chains, then the write.
  async record(callerSaid, modelSaid, { turn, private: keep = false, instructions = null } = {}) {
    const outcome = (word, why = "", rule = null) => ({ outcome: word, why, rule });
    const settled = this._pairing.settle(turn);
    if (!settled) return outcome("interrupted", "the caller moved on before this answer was complete", "Interrupted");
    let answer = new ModelAnswer(callerSaid, modelSaid, null, this._call, { private: keep, instructions, cacheable: settled[1] });
    let verdict = this._rules.answerGiven.firstObjection(answer);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._kept(verdict);
    answer = answer.keyed(this._host._contextKey(callerSaid, answer.text));
    this._host.transcript.push({ role: "user", content: callerSaid });
    this._host.transcript.push({ role: "assistant", content: modelSaid });
    verdict = this._rules.beforeSharing.firstObjection(answer);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._kept(verdict);
    try {
      if (answer.isPersonal) return await this._recordPersonal(answer);
      verdict = this._rules.sharing.firstObjection(answer);
      if (RuleChain.isPending(verdict)) verdict = await verdict;
      if (verdict) return this._kept(verdict);
      const slow = await this._host._learn(answer.key, modelSaid, { ttl: this._host.ttl });
      this._host._lastStored = answer.key;
      if (!slow) this._host._keepQuestion(answer.key, modelSaid); // a slow server gets no extra write
      return slow || outcome("saved");
    } catch (error) {
      this._host.learnErrors += 1;
      return outcome(
        "refused",
        `the server refused the write: ${(error && error.message) || (error && error.name) || String(error)}`,
        "WriteRefused"
      );
    }
  }

  // A personal answer is shared only as a shape with this call's values taken out.
  async _recordPersonal(answer) {
    const personal = this._rules.personal;
    let verdict = personal.check(answer);
    if (!verdict) {
      const templated = await this._host._learnPersonal(answer.key, answer.answer);
      if (templated && templated.outcome) return templated; // slow_write: the shape was not confirmed written
      if (templated) return { outcome: "template", why: "", rule: null };
      verdict = personal.refusal();
    }
    return this._kept(verdict);
  }

  // A save rule kept the answer out of the shared cache.
  _kept(verdict) {
    this._countVerdict(verdict);
    return { outcome: verdict.outcome, why: verdict.reason, rule: verdict.rule };
  }
}

module.exports = { TurnCore };
