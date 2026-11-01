"use strict";

const { COUNTER } = require("../runtime/stats.js");
const { asks, lookupOnly, unfinished } = require("../understanding/wordRules/index.js");
const { TurnDecision } = require("./decision.js");
const { OUTCOME } = require("./outcome.js");

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

module.exports = { VoiceReport };
