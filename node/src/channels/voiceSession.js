"use strict";

const { Agent, voiceAddonMissing } = require("../../agent.js");
const { CrowkisClient } = require("../../index.js");
const { RuleSet } = require("../rules/ruleSet.js");
const { SessionCall } = require("../turns/voice/call.js");
const { BoundedWriter } = require("../runtime/boundedWriter.js");
const { CacheLookup } = require("../runtime/cacheLookup.js");
const { TurnPairing } = require("../runtime/turnPairing.js");
const { TurnDecision } = require("../turns/results.js");
const { OUTCOME } = require("../turns/values.js");
const { TurnCore } = require("../turns/core.js");
const { VoiceAnswered } = require("../turns/results.js");
const { VoiceReader } = require("../turns/voice/turn.js");
const { VoiceReport } = require("../turns/voice/steps.js");
const { VoiceSaving } = require("../turns/voice/steps.js");
const { Stats } = require("../runtime/stats.js");
const { NoRewrite, BudgetedUnderstanding, WordRuleClassifier } = require("../understanding/slots.js");
const { Channel, VOICE } = require("../turns/values.js");
const { KnowledgeSegment } = require("../keys/knowledgeSegment.js");
const { CallState } = require("../state/callState.js");

// The server takes at most this per count in one report.
const REPORT_MAX = 1000000;

const {
  speakable,
  differentSpecifics,
  fill,
  abstract,
  isNonAnswer,
  promptDetails,
  resetPromptBaselines,
  callerDetails,
  repeatsPromptDetails,
} = require("../understanding/wordRules/answers.js");
const { instructs, setsContext, tellsAboutCaller, tellsFacts } = require("../understanding/wordRules/callContext.js");
const { isContextDependent } = require("../understanding/wordRules/followUp.js");
const { carriesCallContext, identifying, IPV4, isPersonal } = require("../understanding/wordRules/personal.js");
const {
  COMMITMENTS,
  PII_PLACEHOLDER,
  normalise,
  wordsOf,
  unknown,
  properNouns,
} = require("../understanding/wordRules/text.js");
const { urgent } = require("../understanding/wordRules/urgent.js");



// Writes a turn stopped waiting for (past twice the latency budget), finishing in the background.
// At most WRITES_MAX wait at once: past it (a hung server) a new answer is not written at all.
let WRITES_MAX = 256;
const pendingWrites = new Set();

/** For tests: every write handed to the background has finished. */
// Question records being written in the background (not capped like answer writes).
const pendingRecords = new Set();

/** Tell the background-write tracker of a question record being written (voice and Chat). */
function trackRecord(record) {
  pendingRecords.add(record);
  record.finally(() => pendingRecords.delete(record));
}

async function waitForWrites() {
  await Promise.allSettled([...pendingWrites, ...pendingRecords]);
}

// For tests: a smaller cap; returns a function that puts the old one back.
function setWritesMax(max) {
  const old = WRITES_MAX;
  WRITES_MAX = max;
  return () => { WRITES_MAX = old; };
}

// How many already-checked caller turns a session remembers for _heard() (past it, a turn is checked again).
const HEARD_MAX = 2048;
// What _recordModelTurn did with an answer; the two that put it in the shared cache.
const STORED = new Set([OUTCOME.SAVED, OUTCOME.TEMPLATE]);


// What VoiceSession.respond() resolves to: read it with `for await` for the text to
// speak, piece by piece as the model writes it. `decision` is ready at once, before the
// first piece: decision.servedFromCache and decision.audio say whether a cached answer
// (and its audio) can be played instead of running the TTS. A response is read once.
class VoiceResponse {
  constructor(session, decision, callerSaid, llm, system, keep) {
    this.decision = decision;
    for (const [name, value] of Object.entries({ session, callerSaid, llm, system, keep })) {
      Object.defineProperty(this, `_${name}`, { value, enumerable: false });
    }
    Object.defineProperty(this, "_pieces", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_closed", { value: false, writable: true, enumerable: false });
  }

  [Symbol.asyncIterator]() {
    if (this._pieces) throw new Error("a VoiceResponse is read once");
    this._pieces = this._run();
    return this._pieces;
  }

  // Stop early: the model's stream is closed and nothing is stored.
  async close() {
    this._closed = true;
    if (!this._pieces) {
      this._pieces = (async function* () {})();
      return;
    }
    await this._pieces.return();
  }

  // The caller talked over this turn, a newer turn was decided, or the app recorded the
  // turn itself: speak no more of this answer.
  _stopped() {
    return this.decision._recorded || this._session._pairing.movedOn(this.decision.turn);
  }

  async *_run() {
    const session = this._session;
    const decision = this.decision;
    if (!decision.needsModel) {
      if (decision.text) yield decision.text;
      return;
    }
    if (this._stopped()) {
      // Talked over before a word was read: never call the model.
      session._interrupted(decision, "");
      return;
    }
    // As answer() does, so a subclass whose decide() returns its own decision works.
    decision._said = this._callerSaid;
    let messages = decision.messages || [...session.injections(), { role: "user", content: this._callerSaid }];
    if (this._system) messages = [{ role: "system", content: this._system }, ...messages];
    let source = await this._llm(messages);
    if (typeof source === "string" || source instanceof String) source = [String(source)];
    let upstream;
    if (source && typeof source[Symbol.asyncIterator] === "function") upstream = source[Symbol.asyncIterator]();
    else if (source && typeof source[Symbol.iterator] === "function") upstream = source[Symbol.iterator]();
    else throw new TypeError("respond() expects the model to give text: a string, or an (async) iterable of text pieces");
    const parts = [];
    let ended = false;
    let movedOn = false;
    try {
      for (;;) {
        const { value: piece, done } = await upstream.next();
        if (done) {
          ended = true;
          break;
        }
        if (piece === null || piece === undefined) continue;
        if (typeof piece !== "string") {
          throw new TypeError(
            `respond() expects the model to give text pieces (strings), got ${typeof piece}; map each chunk to its text first`
          );
        }
        if (this._stopped()) {
          movedOn = true;
          break;
        }
        parts.push(piece);
        if (piece) yield piece;
      }
    } finally {
      if (!ended && typeof upstream.return === "function") {
        try {
          await upstream.return();
        } catch {
          // the model's stream failed to close; nothing of it is kept either way
        }
      }
      if (movedOn) {
        session._interrupted(decision, parts.join(""));
      } else if (ended && !this._closed && !decision._recorded) {
        // A full answer is recorded under answer()'s rules.
        await session._recordDecision(decision, parts.join(""), this._keep, this._system);
      }
    }
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
      commitments = "exact",
      shortTurns = false,
      shareTemplates = false,
      language = "und",
      speed = "1",
      audioFormat = "default",
      bytesPerSecond,
      classifier = null,
      rewriter = null,
      understandBudgetMs = null,
      channel = VOICE,
      knowledgeVersion = "1",
    } = {}
  ) {
    if (!(serveAbove >= 0 && serveAbove <= 1)) {
      throw new Error(`serveAbove must be in 0..1, got ${serveAbove}`);
    }
    if (!Object.prototype.hasOwnProperty.call(COMMITMENTS, commitments)) {
      throw new Error(
        `commitments must be one of ${Object.keys(COMMITMENTS).sort().join(", ")}, got ${commitments}`
      );
    }
    if (latencyBudgetMs !== undefined && latencyBudgetMs !== null && !(latencyBudgetMs > 0)) {
      throw new Error(`latencyBudgetMs must be positive, got ${latencyBudgetMs}`);
    }
    if (understandBudgetMs !== null && understandBudgetMs !== undefined && !(understandBudgetMs > 0)) {
      throw new Error(`understandBudgetMs must be positive, got ${understandBudgetMs}`);
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
    // What changes the sound besides the voice: a clip is reused only when all match (Voice add-on).
    this.language = language;
    this.speed = speed;
    this.audioFormat = audioFormat;
    this.bytesPerSecond = bytesPerSecond;
    // What the channel can do, as the rules read it (a voice call unless a factory says otherwise).
    this.channel = Channel.of(channel);
    // With an understander, answers live in kb=<version>;channel=<name>: switching understanders or
    // knowledge is a deliberate new version (P5). Without one, no segment, as before.
    this._segment = classifier || rewriter ? new KnowledgeSegment(knowledgeVersion, this.channel).segment : null;
    this._reported = {};
    this.serveAbove = serveAbove;
    this.minWords = minWords;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.commitments = commitments;
    this.shortTurns = Boolean(shortTurns);
    // Off by default: a template is cut from an answer the model wrote with the whole
    // call in view, so what is left outside its slots can hold what the caller said.
    this.shareTemplates = Boolean(shareTemplates);
    this.values = Object.create(null);
    this.transcript = [];
    // The counters stats() reports; each public counter property reads and writes one of them.
    this._stats = new Stats();
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
    // Writes the turn stopped waiting for at the latency budget (they finish in the background).
    this.slowWrites = 0;
    // Hits refused because the stored answer was saved for a different question.
    this.differentQuestion = 0;
    this.notShareable = 0;
    this.heldCommitments = 0;
    this.unspeakable = 0;
    this.emptyAnswers = 0;
    this.audioUnavailable = 0;
    this._fillers = new Map();
    // Which turn an answer belongs to: numbering, barge-in and whether its answer may be shared.
    this._pairing = new TurnPairing({ session: this });
    // What this call has heard and how each turn was read; tainted: once the caller tells the call
    // something a later answer may depend on, nothing in it is looked up or shared. Only a session
    // with an understander collects stated turns, facts and private words.
    this.state = new CallState({ remembersTold: Boolean(classifier) });
    // The checks of the three SDK stages, read through this call's view of the session.
    this._rules = classifier ? RuleSet.understood(this._fillers) : RuleSet.voice(this._fillers);
    // How a turn is understood: the word rules, and no rewrite, unless the app plugs in its own.
    this._classifier = classifier || new WordRuleClassifier();
    this._rewriter = rewriter || new NoRewrite();
    // A plugged-in model runs inside its error boundary and budget (null: no deadline); late or
    // failed, the word rules read the turn (counted).
    this._understandingBudgeted = Boolean(classifier || rewriter);
    if (this._understandingBudgeted) {
      const understanding = new BudgetedUnderstanding(this._classifier, this._rewriter, {
        budgetMs: understandBudgetMs ?? null, count: (counter) => this._stats.add(counter),
      });
      this._classifier = understanding;
      this._rewriter = understanding;
    }
    this._call = new SessionCall(this, { track: trackRecord });
    // Writes wait at most twice the budget; the cap is read when a write starts.
    this._writer = new BoundedWriter(pendingWrites, () => WRITES_MAX, (counter) => this._stats.add(counter),
      (message) => console.warn(message));
    // Lookups run inside the budget the call has when it looks up.
    this._cacheLookup = new CacheLookup();
    // The turn's fixed steps; this session keeps the call's transcript, fillers, audio and counters.
    this._core = this._buildCore(this._rules);
    if (values) this.setValues(values);
    if (fillers) this.registerFillers(fillers);
  }

  get _tainted() {
    return this.state.tainted;
  }

  set _tainted(value) {
    this.state.tainted = value;
  }

  get _heardTexts() {
    return this.state.heard;
  }

  /**
   * The one TurnCore with a voice call's parts (this session is their composition root): `rules` are
   * the question, hit and save checks. The session is the core's live settings.
   */
  _buildCore(rules) {
    const report = new VoiceReport(this, this._stats, {
      voiced: (answer, options) => this._voiced(answer, options), pairing: this._pairing, call: this._call,
      state: this.state,
    });
    this._report = report;
    const reader = new VoiceReader({
      classifier: this._classifier, rewriter: this._rewriter,
      state: this.state, call: this._call, segment: this._segment,
    });
    this._saving = new VoiceSaving(this, {
      rules, call: this._call, state: this.state, report, writer: this._writer, stats: this._stats,
      segment: this._segment,
    });
    return new TurnCore(this, {
      pairing: this._pairing, answers: report, reader, questionCheck: rules,
      cacheLookup: this._cacheLookup, hitCheck: rules, report, saving: this._saving,
    });
  }

  setValues(values = {}) {
    for (const [name, value] of Object.entries(values)) {
      if (value === null || value === undefined) delete this.values[name];
      else this.values[name] = String(value);
    }
  }

  registerFiller(trigger, response) {
    const key = normalise(trigger);
    if (!key) throw new Error("a filler trigger must contain something to match on");
    if (!(typeof response === "string" && response.trim())) {
      throw new Error("a filler response must not be empty");
    }
    this._fillers.set(key, response);
  }

  registerFillers(pairs = {}) {
    for (const [trigger, response] of Object.entries(pairs)) {
      this.registerFiller(trigger, response);
    }
  }

  /** What this session decided for the caller's turn (a TurnDecision): the one TurnCore decides. */
  decide(callerSaid) {
    return this._core.decide(callerSaid);
  }

  cancel() {
    return this._pairing.cancel((mark) => {
      this.bargeIns += 1;
      this.transcript.length = mark;
    });
  }

  // Run one caller turn end to end: cache, or the model, then remember the answer.
  // `llm` is called with exactly the messages Crowkis chose for this turn: the
  // question alone (or with the question before it) when the answer may be shared,
  // the whole call when it may not. `system` is the app's own instructions, the
  // same for every caller, and is put first. The returned decision carries the
  // text to speak, from the cache or from the model, and `stored` / `notStored`
  // say whether the model's answer was cached and why not. A model that says
  // nothing sets `empty`: retry, or speak a fallback.
  async answer(callerSaid, llm, { system = null } = {}) {
    const decision = await this.decide(callerSaid);
    if (!decision.needsModel) return decision;
    let messages = decision.messages || [...this.injections(), { role: "user", content: callerSaid }];
    if (system) messages = [{ role: "system", content: system }, ...messages];
    // Straight to the recording step: answer() made this decision itself, so a
    // subclass whose decide() returns its own decision object keeps working.
    decision._said = callerSaid;
    return this._recordDecision(decision, await llm(messages), false, system);
  }

  // Save the answer to a turn you sent to your own model: decide(), then call the
  // model with decision.messages, then record(decision, its answer).
  //
  // The same rules as answer() decide what happens to it: shared with other callers
  // only when decide() said it may be (decision.cacheable), kept to this call
  // otherwise, and dropped when the caller talked over it (cancel()) or a newer turn
  // was decided since. `private: true` keeps a shareable answer to this call, e.g. one
  // built from a tool's result. Never rejects for the server: a refused write is
  // reported, not thrown.
  //
  // Resolves to `decision` with `text` set to the answer and stored / notStored /
  // empty filled in, as answer() does. Rejects for a decision this session did not
  // make, one that did not need the model (served from the cache or a filler), or one
  // already recorded.
  async record(decision, answer, { private: keep = false, system = null } = {}) {
    if (!(decision instanceof TurnDecision)) {
      throw new Error("record() takes the TurnDecision decide() returned");
    }
    if (decision._recorded) throw new Error("record() got a decision that was already recorded");
    const owner = decision._session ? decision._session.deref() : undefined;
    if (owner !== this) {
      throw new Error(
        decision._session
          ? "record() got a decision from another session: each call's answers are recorded in the session that decided them"
          : "record() takes a decision from this session's decide(); one from another session (another call) or made by hand is refused"
      );
    }
    if (!decision.needsModel) {
      throw new Error(
        `record() is for a turn that needed the model; this one was answered by ${
          decision.servedFromFiller ? "a filler" : "the cache"
        } ("${decision.action}")`
      );
    }
    return this._recordDecision(decision, answer, keep, system);
  }

  // record() and answer(): store the answer and fill in the decision.
  async _recordDecision(decision, answer, keep, system = null) {
    decision._recorded = true;
    const said = decision._said;
    decision._said = null;
    decision.text = answer;
    const { outcome, why: reason, rule } = await this._record(said, answer, {
      turn: decision.turn,
      private: keep,
      instructions: system,
    });
    decision.stored = STORED.has(outcome);
    decision.saveRule = decision.stored ? null : rule || null;
    const why = decision.stored ? "" : reason || outcome;
    decision.notStored = why;
    if (!(typeof decision.text === "string" && decision.text.trim())) {
      decision._empty = true;
      decision.reason = "the model returned an empty answer; retry or speak a fallback";
    } else if (why) {
      decision.reason = `${decision.reason}; not stored: ${why}`;
    }
    return decision;
  }

  // answer(), streamed: decide now, then give the text to speak piece by piece.
  //
  // llm(messages) gives the model's text as it writes it: an async iterable or iterable
  // of strings (null pieces are skipped), or the whole answer as a string (or a promise
  // of one). It is called with the same messages answer() would use, only when the turn
  // needs the model, and only once the response is read.
  //
  // A turn the cache or a filler answers yields that text once (decision.audio has its
  // audio when the session caches audio). A model turn yields the model's pieces and,
  // when its stream ends, records the full answer under answer()'s rules (`private` as
  // in record()). If the caller talks over it (cancel()) or a newer turn is decided, the
  // stream stops at the next piece, the model's stream is closed and nothing is stored.
  // A model error rejects and stores nothing, as does stopping early (close(), or
  // leaving the loop); the decision can then still be recorded with record().
  async respond(callerSaid, llm, { system = null, private: keep = false } = {}) {
    const decision = await this.decide(callerSaid);
    return new VoiceResponse(this, decision, callerSaid, llm, system, keep);
  }

  // A streamed turn the caller talked over: report it, store and keep nothing. Not an
  // empty answer, so an app never retries over the caller's new words.
  _interrupted(decision, spoken) {
    if (decision._recorded) return;
    decision._recorded = true;
    decision._said = null;
    decision.text = spoken;
    decision.stored = false;
    decision.saveRule = "Interrupted";
    this._stats.countRule("Interrupted");
    decision.notStored = "the caller moved on before this answer was complete";
    decision.reason = `${decision.reason}; not stored: ${decision.notStored}`;
  }

  // Keep a turn in this call's transcript and never cache it. For a model that
  // holds the whole conversation itself (a realtime speech model): it cannot be
  // given decision.messages, so nothing it says is shared.
  recordPrivateTurn(callerSaid, modelSaid) {
    this._heard(callerSaid);
    if (this._pairing.cancelled) return;
    this._pairing.isOpen = false;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (this._pairing.dropShareable()) this.notShareable += 1;
  }

  // A caller turn this session never decided (a private turn, history the app gave the
  // model): one that tells the call something a later answer may depend on keeps the
  // rest of the call off the shared cache, as decide() does for its own turns.
  _heard(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (this._tainted || !text || this._heardTexts.has(text)) return;
    if (this._heardTexts.size < HEARD_MAX) this._heardTexts.add(text);
    if (setsContext(text)) this._tainted = true;
  }

  // Record the model's answer to the turn decide() last handled, and cache it if
  // allowed. Only an answer written from decision.messages reaches this, so it is
  // shared exactly when decide() said it may be. `turn` is the decision's turn: an
  // answer to a turn the caller talked over, or to one before the latest, is
  // dropped, so it never lands on later words. Never rejects: a refused write
  // (security pipeline, tenant limit, cache down) must not end a call.
  //
  // Resolves to what happened to the answer: "saved" (shared), "template" (shared
  // as a shape, this caller's values removed), "kept" (the model read the whole
  // call, so it stays in this call), "private" (personal, or repeats this caller's
  // details), "non_answer", "not_saved" (a follow-up with nothing to key it to),
  // "refused" (the write failed), "slow_write" (a session with a latency budget stopped
  // waiting for the write: not confirmed) or "interrupted" (talked over, or the caller
  // moved on before it was complete).
  async _recordModelTurn(callerSaid, modelSaid, { turn, private: keep = false } = {}) {
    return (await this._core.record(new VoiceAnswered(callerSaid, modelSaid, turn, keep, null))).outcome;
  }

  // The same, with why an answer was not stored, in words, and the rule that decided it.
  _record(callerSaid, modelSaid, { turn, private: keep = false, instructions = null } = {}) {
    return this._core.record(new VoiceAnswered(callerSaid, modelSaid, turn, keep, instructions));
  }

  injections() {
    return this.transcript.slice();
  }

  /** The counts the Voice page shows, by the server's names. */
  _reportable() {
    return {
      turns: this.served + this.inferred + this.filled,
      served_from_cache: this.served,
      filler_hits: this.filled,
      model_calls_avoided: this.served + this.filled,
      private_turns: this.refusedPrivate + this.uncacheablePersonal,
      barge_ins: this.bargeIns,
      latency_misses: this.overBudget,
      empty_answers: this.emptyAnswers,
    };
  }

  /**
   * Send this session's counts since its last report to the Voice page (the server's Voice add-on).
   * false when the server has no Voice add-on. Nothing is lost: what a failed report did not send
   * goes with the next.
   */
  async reportStats() {
    const now = this._reportable();
    const sent = {};
    for (const [name, count] of Object.entries(now)) {
      const fresh = count - (this._reported[name] || 0);
      if (fresh > 0) sent[name] = Math.min(fresh, REPORT_MAX);
    }
    if (!Object.keys(sent).length) return true;
    try {
      await this.agent.client.cvoicestat(sent, { tenant: this.agent.tenant });
    } catch (error) {
      if (voiceAddonMissing(error)) return false;
      throw error;
    }
    for (const [name, count] of Object.entries(sent)) this._reported[name] = (this._reported[name] || 0) + count;
    return true;
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
      slowWrites: this.slowWrites,
      differentQuestion: this.differentQuestion,
      notShareable: this.notShareable,
      commitmentsSentToModel: this.heldCommitments,
      unspeakableAnswers: this.unspeakable,
      emptyAnswers: this.emptyAnswers,
      audioUnavailable: this.audioUnavailable,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
      // How often each rule decided a turn or kept an answer, by the rule's name.
      rules: this._stats.ruleCounts(),
      // Turns a plugged-in model was too slow for or failed on (the word rules read them).
      ...(this._understandingBudgeted
        ? { understandTimeouts: this.understandTimeouts, understandErrors: this.understandErrors }
        : {}),
    };
  }

  // The audio for an answer this turn speaks, or null. Never rejects: when the audio
  // step fails (the cache, or the app's own synthesiser) the turn keeps its text and the
  // app's TTS speaks it. It used to reject the whole turn, losing the cached answer.
  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    try {
      return await this._voice(answer, cacheable);
    } catch (error) {
      this.audioUnavailable += 1;
      // The type only: an app's TTS error can quote the (possibly personal) text.
      console.warn(`crowkis voice: no audio for this answer, the text is still served (${(error && error.name) || typeof error})`);
      return null;
    }
  }

  async _voice(answer, cacheable) {
    // A text-only session (voiceSession() with no voice) has no real voice id to key a
    // clip on: speak, but never read or store a cached clip.
    if (!cacheable || this._textOnly) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
      language: this.language,
      speed: this.speed,
      audioFormat: this.audioFormat,
      bytesPerSecond: this.bytesPerSecond,
    });
  }
}

/**
 * Fill the cache from past calls, so it is useful on the first day.
 *
 * `calls` is an iterable of calls, each an array of `[callerSaid, agentSaid]`
 * turns in order. A follow-up is kept with the turn it depends on, and nothing
 * is spoken or synthesised.
 *
 * It needs the server's decision engine, holding answers until it has judged
 * them (the default), and throws otherwise. A past agent turn can hold
 * details the caller never said aloud (an address looked up, a balance),
 * which the live rules cannot see in a transcript; the engine reads every
 * answer before anyone is served it.
 *
 * Resolves to totals. After each call it gives the engine up to `wait`
 * seconds to catch up; `stalled` is true when it stopped early because three
 * calls in a row were not judged in that time.
 */
async function warmFromCalls(agent, calls, { wait = 30 } = {}) {
  if (!((await agent.decides()) && agent._holds)) {
    throw new Error(
      "warmFromCalls needs the server's decision engine, holding answers until it has judged " +
        "them (CROWKIS_DECIDE_UPSTREAM set, CROWKIS_DECIDE_SERVE_UNJUDGED not set): otherwise a " +
        "past answer holding one caller's details could be shared before it is checked"
    );
  }
  const totals = { calls: 0, turns: 0, keptPrivate: 0, failedWrites: 0, stalled: false };
  let stalls = 0;
  for (const call of calls) {
    const session = new VoiceSession(agent, { voice: "warm-start" });
    const earlier = [];
    for (const [callerSaid, agentSaid] of call) {
      // The same rule as a live turn picks the candidates. A past answer was
      // written with the whole call in view, so one that repeats what
      // identified this caller is kept out here, and the engine reads the rest
      // before anyone is served them.
      const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
      const keyed = session._call.contextKey(callerSaid, text) || callerSaid;
      session._tainted = session._tainted || setsContext(text);
      session._pairing.offer(
        session._pairing.turn,
        session._report.modelMessages(callerSaid)[1] && !carriesCallContext(agentSaid, keyed, earlier),
      );
      await session._recordModelTurn(callerSaid, agentSaid);
      earlier.push(callerSaid);
      totals.turns += 1;
    }
    totals.calls += 1;
    totals.keptPrivate += session.notShareable + session.uncacheablePersonal;
    totals.failedWrites += session.learnErrors;
    // Let the engine catch up before the next call: it judges a bounded
    // number of answers at a time and refuses what does not fit.
    stalls = (await judgedInTime(agent, session._saving.lastStored, wait * 1000)) ? 0 : stalls + 1;
    if (stalls >= 3) {
      totals.stalled = true;
      break;
    }
  }
  return totals;
}

/** False when the engine was still working on `query` after `ms`. */
async function judgedInTime(agent, query, ms) {
  const deadline = Date.now() + ms;
  while (query && Date.now() < deadline) {
    let view;
    try {
      view = await agent.explain(query);
    } catch (_error) {
      // Cannot ask, so there is nothing to wait for.
      return true;
    }
    if (!(view && view.pending)) return true;
    await new Promise((resolve) => setTimeout(resolve, Math.min(200, ms)));
  }
  return !query;
}

// The voice id of a text-only session. Never used as a cache key: every audio path
// checks `_textOnly` first.
const TEXT_ONLY_VOICE = "crowkis:text-only";

// Every option new VoiceSession() takes, so a misspelt one is an error here, as in Python.
const SESSION_OPTIONS = new Set([
  "serveAbove", "minWords", "synthesise", "ttl", "fillers", "values", "commitments",
  "shortTurns", "shareTemplates", "language", "speed", "audioFormat", "bytesPerSecond",
  "classifier", "rewriter", "understandBudgetMs", "channel", "knowledgeVersion",
]);

/**
 * A ready VoiceSession in one call, with defaults for live calls (same as Python's
 * crowkis.voice_session()).
 *
 * It builds the client and the Agent itself. Server settings not passed here come from
 * the environment, then the defaults (see the README, "Connect to your server"). The
 * defaults differ from a bare VoiceSession because a caller is waiting:
 * - latencyBudgetMs 250: the longest a turn waits for a cache lookup before it goes to
 *   the model. null turns the budget off.
 * - timeoutMs 1000 per server request, with no retries. Saving the model's answer
 *   happens while the caller waits; 5 s tried three times would leave a stuck server
 *   holding the turn for about 15 s. The cost of no retries: a request that fails once
 *   (the first after a server restart, or a BUSY reply) is not tried again, so that
 *   lookup goes to the model or that answer is not stored. Pass your own `client` for
 *   other settings, e.g. for warmFromCalls, which should not use this live-call client.
 *
 * `voice` is the TTS voice id. Without it the session caches text only and never reads
 * or stores audio, so two voices can never share a clip; passing `synthesise` then is
 * an error. Every other VoiceSession option is passed on as it is.
 *
 * `client` uses a client you built, as it is: passing host/port/authToken/token/tenant/
 * timeoutMs with it is an error, and closing the agent leaves it open.
 *
 * `classifier` / `rewriter` plug in a model that reads the turn (LLMClassifier, LLMRewriter,
 * ReplayRewriter). It gets `understandBudgetMs` (250) per turn; late or failed, the word rules read
 * the turn. The word rules apply either way, so a model can make a call more private, never less.
 * null turns the budget off.
 *
 * `channel` ("voice", the default, or "realtime", or a Channel) is the profile the budgets not
 * passed here come from (voice and realtime: 250 ms each).
 */
function voiceSession(options = {}) {
  const {
    voice,
    agentId = "voice",
    client: given,
    host,
    port,
    authToken,
    auth_token: authTokenAlias,
    token,
    tenant,
    timeoutMs,
    channel: channelOption = VOICE,
    latencyBudgetMs,
    understandBudgetMs,
    ...rest
  } = options;
  if (timeoutMs !== undefined && timeoutMs !== null && !(timeoutMs > 0)) {
    throw new Error(`timeoutMs must be a positive number of milliseconds, got ${timeoutMs}`);
  }
  const unknown = Object.keys(rest).filter((name) => !SESSION_OPTIONS.has(name));
  if (unknown.length) {
    throw new TypeError(`voiceSession() got unknown option(s): ${unknown.join(", ")}`);
  }
  if (given) {
    const passed = Object.entries({ host, port, authToken, auth_token: authTokenAlias, token, tenant, timeoutMs })
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([name]) => name);
    if (passed.length) {
      throw new Error(
        `voiceSession() got client and ${passed.join(", ")}: a client passed in is used as it is, ` +
          "so set these on the client instead"
      );
    }
  }
  const channel = Channel.of(channelOption);
  const textOnly = voice === undefined || voice === null;
  if (textOnly && rest.synthesise) {
    throw new Error(
      "voiceSession() got synthesise without voice. Cached audio is keyed on the voice that " +
        "spoke it: pass your TTS voice id, or leave out synthesise to cache text only"
    );
  }
  const client =
    given ||
    new CrowkisClient({
      host,
      port,
      authToken: authToken || authTokenAlias || token,
      tenant,
      timeoutMs: timeoutMs ?? 1000,
      maxRetries: 0,
    });
  const agent = new Agent(agentId, { client, tenant: client.tenant });
  agent._ownsClient = !given;
  const session = new VoiceSession(agent, {
    ...rest,
    voice: textOnly ? TEXT_ONLY_VOICE : voice,
    // Budgets left out come from the channel's profile; null turns one off.
    latencyBudgetMs: latencyBudgetMs === undefined ? channel.budgetMs : latencyBudgetMs,
    understandBudgetMs: understandBudgetMs === undefined ? channel.understandBudgetMs : understandBudgetMs,
    channel,
  });
  session._textOnly = textOnly;
  return session;
}

// The public counters (session.filled, ...) read and write the session's Stats.
Stats.defineCounterProperties(VoiceSession.prototype);

module.exports = {
  VoiceSession,
  VoiceResponse,
  TurnDecision,
  voiceSession,
  warmFromCalls,
  _SESSION_OPTIONS: SESSION_OPTIONS,
  _speakable: speakable,
  _words: wordsOf,
  _promptDetails: promptDetails,
  _repeatsPromptDetails: repeatsPromptDetails,
  _callerDetails: callerDetails,
  _resetPromptBaselines: resetPromptBaselines,
  _differentSpecifics: differentSpecifics,
  _waitForWrites: waitForWrites,
  _trackRecord: trackRecord,
  _pendingWrites: pendingWrites,
  _writesMax: () => WRITES_MAX,
  _setWritesMax: setWritesMax,
  _isPersonal: isPersonal,
  _IPV4: IPV4,
  _PII_PLACEHOLDER: PII_PLACEHOLDER,
  _isContextDependent: isContextDependent,
  _setsContext: setsContext,
  _tellsFacts: tellsFacts,
  _tellsAboutCaller: tellsAboutCaller,
  _instructs: instructs,
  _urgent: urgent,
  _wordsOf: wordsOf,
  _identifying: identifying,
  _properNouns: properNouns,
  _isNonAnswer: isNonAnswer,
  _abstract: abstract,
  _fill: fill,
};
