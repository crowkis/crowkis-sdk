"use strict";

// Voice's report and saving steps for TurnCore.

const { COUNTER } = require("../../runtime/stats.js");
const { SLOT, abstract, slotNames } = require("../../understanding/wordRules/answers.js");
const { unfinished } = require("../../understanding/wordRules/followUp.js");
const {
  carriesCallContext,
  leaks,
  EMAIL,
  asks,
  identifies,
  lookupOnly,
  readsOutDigits,
} = require("../../understanding/wordRules/personal.js");
const { AMOUNT_WORDS, MATTERS, hasDigit, wordsOf } = require("../../understanding/wordRules/text.js");
const { isThenable } = require("../core.js");
const { TurnDecision } = require("../results.js");
const { Checked, OUTCOME } = require("../values.js");
const { ModelAnswer } = require("./turn.js");

const SERVED_REASON = "confident cache hit";
const WRITE_REFUSED = "WriteRefused";

/**
 * Adapter: what TurnCore found, as a voice call reports it: a TurnDecision for a turn and an outcome
 * ({ outcome, why, rule }) for an answer, counted in Stats. A served turn joins the transcript and
 * carries its audio when the session caches audio. A rule that answered the turn itself (a filler) is
 * the only early answer voice has. `voiced` is the session's audio for an answer (null without it).
 *
 * Every decision carries its turn's number and the session that made it; a model turn also what the
 * model reads (modelMessages), and whether its answer may be shared is offered to the call's
 * `pairing` for that turn.
 */
class VoiceReport {
  /**
   * @param {{ transcript: object[] }} session read live
   * @param {import("../runtime/stats.js").Stats} stats
   */
  constructor(session, stats, { voiced, pairing, call, state }) {
    this._session = session;
    // A WeakRef, so a kept decision never keeps a call alive.
    this._owner = new WeakRef(session);
    this._stats = stats;
    this._voiced = voiced;
    this._pairing = pairing;
    this._call = call;
    this._state = state;
  }

  /** Voice reads every turn first (its fillers are checked once the turn is read). */
  beforeReading() {
    return null;
  }

  /** A registered filler answers the turn at once (its audio may be shared); null for any other objection. */
  afterCheck(checked) {
    if (checked.objection.answer === null || checked.objection.answer === undefined) return null;
    return this._filler(checked);
  }

  toModel(checked) {
    return this._handed(this._infer(checked.objection), checked.subject);
  }

  missed(checked, looked) {
    return this._handed(this._infer(looked.objection, looked.hit ? looked.hit.confidence : 0), checked.subject);
  }

  async served(checked, looked) {
    const turn = checked.subject;
    const cached = looked.cached;
    this._stats.add(COUNTER.SERVED);
    this._session.transcript.push({ role: "user", content: turn.said });
    this._session.transcript.push({ role: "assistant", content: cached.answer });
    const decision = new TurnDecision("serve", {
      text: cached.answer,
      audio: await this._voiced(cached.answer, { cacheable: !turn.isPersonal }),
      confidence: looked.hit.confidence,
      reason: SERVED_REASON,
    });
    decision._audioShareable = !turn.isPersonal;
    return this._handed(decision, turn);
  }

  /** A save rule (or the pairing) kept the answer out of the shared cache. */
  kept(verdict) {
    this._count(verdict);
    return { outcome: verdict.outcome, why: verdict.reason, rule: verdict.rule };
  }

  refused(error) {
    this._stats.add(COUNTER.LEARN_ERRORS);
    const why = `the server refused the write: ${(error && error.message) || (error && error.name) || String(error)}`;
    return { outcome: OUTCOME.REFUSED, why, rule: WRITE_REFUSED };
  }

  /** The rule that kept an answer out of the shared cache is counted in stats(). */
  recorded(answered, outcome) {
    if (outcome.rule) this._stats.countRule(outcome.rule);
    return outcome;
  }

  /**
   * What the model should read to answer this turn, and whether that answer may be cached. A shared
   * answer is only safe when the model saw nothing but the cache key: the question, and for a
   * follow-up the questions it leans on. Personal turns, and follow-ups to one, get the whole call and
   * are never shared.
   */
  modelMessages(said) {
    const call = this._call;
    const text = typeof said === "string" ? said.trim() : "";
    if (
      call.tainted || text.split(/\s+/).filter(Boolean).length < call.minWords ||
      this._state.isPersonal(text) || lookupOnly(text) ||
      call.afterUrgent(text) || unfinished(text)
    ) {
      return [null, false];
    }
    if (!this._state.isContextDependent(text)) {
      // "Twelve years old.": a turn that neither asks nor requests anything is an
      // answer about the caller, never stored on its own.
      if (!asks(text)) return [null, false];
      return [[{ role: "user", content: said }], true];
    }
    const chain = call.chain();
    if (chain === null || this._state.chainIsPrivate(chain, call.minWords)) return [null, false];
    return [[...chain, said].map((turn) => ({ role: "user", content: turn })), true];
  }

  // A registered filler's answer, with its audio.
  async _filler(checked) {
    const verdict = checked.objection;
    this._count(verdict);
    const decision = new TurnDecision(verdict.route, {
      text: verdict.answer,
      audio: await this._voiced(verdict.answer),
      confidence: 1,
      reason: verdict.reason,
      rule: verdict.rule,
    });
    decision._audioShareable = true;
    return this._handed(decision, checked.subject);
  }

  // The decision for turn `turn.number`, made by this session; for a model turn, what the model
  // reads. Whether its answer may be shared is offered to the pairing.
  _handed(decision, turn) {
    decision.turn = turn.number;
    decision._session = this._owner;
    if (decision.needsModel) {
      decision._said = turn.said;
      [decision.messages, decision.cacheable] = this.modelMessages(turn.said);
    }
    this._pairing.offer(turn.number, decision.cacheable);
    return decision;
  }

  // The model answers this turn: `verdict` says which rule decided so, and why.
  _infer(verdict, confidence = 0) {
    this._count(verdict);
    this._stats.countRule(verdict.rule);
    return new TurnDecision("infer", { confidence, reason: verdict.reason, rule: verdict.rule });
  }

  _count(verdict) {
    for (const counter of verdict.counts) this._stats.add(counter);
  }
}

/**
 * check(): the answer as the save rules read it: `answerGiven` first, then, once it is known to be an
 * answer, its cache key and its place in the transcript, then `beforeSharing`.
 * write(): the shared form of the answer and its write (the writer's boundary turns a failed one into
 * the refused outcome): a personal
 * answer only as a shape with this call's values taken out (`personal`, and only when the session
 * shares templates), any other after the `sharing` rules; through the bounded write (in the call's
 * `segment`, if any), with the question it was saved for. `lastStored` is the question the latest
 * shared answer was stored under. `session` is read live (agent, latencyBudgetMs, ttl, shareTemplates,
 * values, transcript): an app may change them between turns.
 */
class VoiceSaving {
  constructor(session, { rules, call, state, report, writer, stats, segment }) {
    this._session = session;
    this._rules = rules;
    this._call = call;
    this._state = state;
    this._report = report;
    this._writer = writer;
    this._stats = stats;
    this._segment = segment;
    this.lastStored = null;
  }

  check(answered) {
    const answer = new ModelAnswer(answered.said, answered.modelSaid, null, this._call, {
      private: answered.private, instructions: answered.instructions, cacheable: answered.shareable && !answered.private,
    });
    const verdict = this._rules.answerGiven.firstObjection(answer);
    if (isThenable(verdict)) return verdict.then((given) => (given ? new Checked(answer, given) : this._keyed(answered, answer)));
    if (verdict) return new Checked(answer, verdict);
    return this._keyed(answered, answer);
  }

  async write(answer) {
    if (answer.isPersonal) return await this._writePersonal(answer);
    let verdict = this._rules.sharing.firstObjection(answer);
    if (isThenable(verdict)) verdict = await verdict;
    if (verdict) return this._report.kept(verdict);
    const written = await this._learn(answer.key, answer.answer, { ttl: this._session.ttl });
    if (written.refused) return this._report.refused(written.error);
    if (!(written.objection && written.objection.rule === "NotStored")) this.lastStored = answer.key; // a key the server kept nothing under is not waited for
    if (!written.written) return this._report.kept(written.objection); // a slow server gets no extra write
    this._call.questionRecords().keep(answer.key, answer.answer, this._session.ttl);
    return { outcome: OUTCOME.SAVED, why: "", rule: null };
  }

  // Once it is known to be an answer: its cache key (worked out before it joins the transcript), then
  // its place in the transcript; `beforeSharing`'s objection may still be pending.
  _keyed(answered, answer) {
    answer.key = this._state.rewrittenFor(answer.text) ?? this._call.contextKey(answered.said, answer.text);
    this._session.transcript.push({ role: "user", content: answered.said });
    this._session.transcript.push({ role: "assistant", content: answered.modelSaid });
    return new Checked(answer, this._rules.beforeSharing.firstObjection(answer));
  }

  // agent.learn() through the bounded write (twice the latency budget; waited for without one), in the
  // call's segment; resolves to a WriteResult. Not async: the caller awaits the writer's own promise,
  // with no extra step between.
  _learn(key, answer, options) {
    const learnOptions = this._segment ? { segment: this._segment, ...options } : options;
    return this._writer.writeWithin(() => this._session.agent.learn(key, answer, learnOptions), this._session.latencyBudgetMs);
  }

  // A personal answer is shared only as a shape with this call's values taken out.
  async _writePersonal(answer) {
    const personal = this._rules.personal;
    let verdict = personal.check(answer);
    if (!verdict) {
      const templated = await this._learnPersonal(answer.key, answer.answer);
      if (templated === null) verdict = personal.refusal();
      else if (templated.written) return { outcome: OUTCOME.TEMPLATE, why: "", rule: null };
      else if (templated.refused) return this._report.refused(templated.error);
      else verdict = templated.objection; // slow_write: the shape was not confirmed written
    }
    return this._report.kept(verdict);
  }

  // Store a personal answer as a shape: what the write did (a WriteResult), or null (nothing written)
  // when it cannot be made generic, or when this session does not share templates.
  async _learnPersonal(keyed, modelSaid) {
    const session = this._session;
    if (!session.shareTemplates) {
      this._stats.add(COUNTER.UNCACHEABLE_PERSONAL);
      return null;
    }
    const shaped = abstract(modelSaid, session.values);
    // The model read the whole call: what is left outside the slots must say nothing
    // of this caller that was not declared (a name, an address, a number, a matter).
    const outside = shaped.replace(SLOT, " ");
    const words = wordsOf(outside);
    const earlier = session.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    const undeclared =
      words.some((w) => hasDigit(w) || AMOUNT_WORDS.has(w) || MATTERS.has(w)) ||
      readsOutDigits(outside, words) || EMAIL.test(outside) || identifies(outside, words) ||
      carriesCallContext(outside, keyed, earlier);
    if (this._call.hasValues && slotNames(shaped).length && !leaks(shaped, session.values) && !undeclared) {
      return await this._learn(keyed, shaped, { ttl: session.ttl, template: true });
    }
    this._stats.add(COUNTER.UNCACHEABLE_PERSONAL);
    return null;
  }
}

module.exports = { VoiceReport, VoiceSaving };
