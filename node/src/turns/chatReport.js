"use strict";

const { OUTCOME, because } = require("./outcome.js");
const { SHARED } = require("./routes.js");
const { TurnResult } = require("./turnResult.js");

const HIT_REASON = "cache hit";
const MISS_REASON = "cache miss";
const WRITE_FAILED = because(OUTCOME.REFUSED, "write_failed");
const SAVE_REFUSED = "save_refused";

/**
 * Adapter: what TurnCore found, as a chat reports it: a TurnResult for a turn (one the agent must
 * answer awaits it in ChatTurns), an outcome string for an answer, the `counts` each verdict names, a
 * "turn" event (an "answer" event once recorded), and the agent's reply noted in the chat's state
 * when it is already known (a hit). `session` is read live (state, counts, emit).
 */
class ChatReport {
  constructor(session, turns) {
    this._session = session;
    this._turns = turns;
  }

  toModel(checked) {
    const reading = checked.subject;
    this._session.emit({ ...this._event(reading), hit: false });
    return this._turns.awaitAnswer(new TurnResult(reading.turnId, reading.verdict.route, {
      frame: reading.frame, verdict: reading.verdict, reason: reading.verdict.reasons.join(";"),
    }));
  }

  missed(checked, looked) {
    const reading = checked.subject;
    this.count(looked.objection);
    this._session.emit({ ...this._event(reading), hit: false });
    return this._turns.awaitAnswer(new TurnResult(reading.turnId, SHARED, {
      frame: reading.frame, verdict: reading.verdict, messages: this._messages(reading), reason: MISS_REASON,
    }));
  }

  served(checked, looked) {
    const reading = checked.subject;
    const answer = looked.hit.answer;
    this._session.counts.hits += 1;
    this._session.state.noteAgentReply(answer);
    this._session.emit({ ...this._event(reading), hit: true });
    return this._turns.awaitAnswer(new TurnResult(reading.turnId, SHARED, {
      text: answer, needsModel: false, frame: reading.frame, verdict: reading.verdict, reason: HIT_REASON,
    }));
  }

  kept(verdict) {
    this.count(verdict);
    return verdict.outcome;
  }

  refused() {
    this._session.counts[SAVE_REFUSED] += 1;
    return WRITE_FAILED;
  }

  /** The "answer" event, whatever happened to the answer. */
  recorded(answered, outcome) {
    const result = answered.result;
    this._session.emit({ type: "answer", turnId: result.turnId, route: result.route, outcome, key: result.verdict ? result.verdict.key : null });
    return outcome;
  }

  /** Add to the counters `verdict` names. */
  count(verdict) {
    const counts = this._session.counts;
    for (const name of verdict.counts) counts[name] = (counts[name] || 0) + 1;
  }

  // What the model reads for a shared question: the question alone, with the attributes in its key and
  // the reply language as a system note.
  _messages(reading) {
    const verdict = reading.verdict;
    const messages = [{ role: "user", content: verdict.question }];
    const notes = [];
    const attrs = Object.entries(verdict.attributes).sort();
    if (attrs.length) notes.push(`Answer for: ${attrs.map(([k, v]) => `${k}: ${v}`).join("; ")}.`);
    const language = this._session.state.language || reading.frame.language;
    if (language) notes.push(`Reply in this language: ${language}.`);
    if (notes.length) messages.unshift({ role: "system", content: notes.join(" ") });
    return messages;
  }

  _event(reading) {
    const { verdict, frame } = reading;
    return {
      type: "turn", turnId: reading.turnId, route: verdict.route, reasons: [...verdict.reasons], shared: verdict.shared,
      urgent: frame.urgent, kind: frame.kind, confidence: frame.confidence, question: verdict.question,
      key: verdict.key, questionType: verdict.shared ? frame.questionType : null,
    };
  }
}

module.exports = { ChatReport, SAVE_REFUSED };
