"use strict";

// Chat's turn numbering, answers, report and saving steps for TurnCore.

const { masked, norm } = require("../../understanding/chatDetails.js");
const { AGENT, FILLER, PERSONAL, SHARED, TOOLS, TurnResult, URGENT } = require("../results.js");
const { Checked, OUTCOME, Verdict, because } = require("../values.js");
const { ChatAnswer } = require("./turn.js");

const CANCELLED_COUNT = "cancelled";
const CANCELLED_VERDICT = new Verdict("Cancelled", "the user talked over this turn", [CANCELLED_COUNT], OUTCOME.CANCELLED);
// An older turn finishing after a newer one started: never saved.
const STALE_VERDICT = new Verdict("Stale", "a newer turn awaits the answer", [], OUTCOME.STALE);

/**
 * A chat's turns, as TurnCore's Pairing. Every turn gets the next number (open). A turn the agent
 * must answer awaits it (awaitAnswer); a filler, an urgent script or a tools answer does not, so the
 * turn before it still does. An answer is paired only with the turn awaiting one, and never with a
 * cancelled turn (a barge-in). `nextTurn` is kept with an exported thread.
 */
class ChatTurns {
  constructor() {
    this.nextTurn = 1;
    this._awaiting = null;
    this._cancelled = new Set();
  }

  open() {
    const turn = this.nextTurn;
    this.nextTurn += 1;
    return turn;
  }

  /** `result`'s turn is the one the agent's next answer belongs to. */
  awaitAnswer(result) {
    this._awaiting = result;
    return result;
  }

  settle(answered) {
    const turnId = answered.result.turnId;
    if (this._cancelled.has(turnId)) return new Checked(answered, CANCELLED_VERDICT);
    if (!this._awaiting || this._awaiting.turnId !== turnId) return new Checked(answered, STALE_VERDICT);
    this._awaiting = null;
    return new Checked(answered);
  }

  /** Barge-in: the turn awaiting an answer is abandoned and its answer will never be saved. */
  cancel() {
    if (!this._awaiting) return false;
    this._cancelled.add(this._awaiting.turnId);
    this._awaiting = null;
    return true;
  }
}

const SHARING_OFF = "off";
const URGENT_SCRIPT_REASON = "urgent script";
const TOOLS_REASON = "answered by the business's tools";

// The app's hooks, each inside its one error boundary: a failing urgent or monitoring hook changes nothing and a
// failing tool means the model answers. urgent and tools await the hook and hand the result on in the same step.
async function urgentHook(session, text, frame, then) {
  try { await session.onUrgent(text, frame); } catch { /* the hook must not take the call down */ }
  return then();
}

async function toolsHook(session, text, frame, then) {
  let answered = null;
  try { answered = await session.onTools(text, frame); } catch { answered = null; /* a failing tool means the model answers */ }
  return then(answered);
}

function eventHook(session, event) {
  try { session.onEvent(event); } catch { /* monitoring must never affect the call */ }
}

/**
 * What a chat answers without the cache or the model, as TurnCore's EarlyAnswers. Before a turn is
 * read: an empty turn goes to the agent, a registered filler answers it, and with sharing off the
 * agent answers everything. After the check: the app's `onUrgent` hook runs on an urgent turn and its
 * `urgentReply` answers it; `onTools` may answer a personal or live turn. None of these is ever
 * cached; a hook that fails never ends the chat (`urgentHook`, `toolsHook`, `eventHook`). `session` is read live (state, counts, mode, fillers,
 * the hooks, emit).
 */
class ChatAnswers {
  constructor(session, turns) {
    this._session = session;
    this._turns = turns;
  }

  beforeReading(said, turnId) {
    const session = this._session;
    const text = String(said || "").split(/\s+/).filter(Boolean).join(" ");
    if (!text) return this._turns.awaitAnswer(new TurnResult(turnId, AGENT, { reason: "empty" }));
    const filler = session.fillers.get(norm(text));
    if (filler !== undefined) {
      session.counts[FILLER] += 1;
      session.state.noteAgentReply(filler);
      return new TurnResult(turnId, FILLER, { text: filler, needsModel: false, reason: "registered filler" });
    }
    if (session.mode === SHARING_OFF) {
      session.counts.sharing_off += 1;
      session.emit({ type: "turn", turnId, route: AGENT, reasons: ["mode_off"], shared: false });
      return this._turns.awaitAnswer(new TurnResult(turnId, AGENT, { reason: "sharing off" }));
    }
    return null;
  }

  /** The urgent or tools answer for a turn the check stopped, or null (the model answers). */
  afterCheck(checked) {
    const reading = checked.subject;
    const route = reading.verdict.route;
    if (route === URGENT) return this._urgent(reading);
    if (route === TOOLS || route === PERSONAL) return this._tools(reading);
    return null;
  }

  // The app's hook is awaited only when there is one; the reply follows it.
  _urgent(reading) {
    return this._session.onUrgent
      ? urgentHook(this._session, reading.text, reading.frame, () => this._urgentReply(reading))
      : this._urgentReply(reading);
  }

  _urgentReply(reading) {
    const session = this._session;
    if (!session.urgentReply) return null;
    session.state.noteAgentReply(session.urgentReply);
    return new TurnResult(reading.turnId, URGENT, {
      text: session.urgentReply, needsModel: false, frame: reading.frame, verdict: reading.verdict, reason: URGENT_SCRIPT_REASON,
    });
  }

  // Without the app's tools the model answers at once.
  _tools(reading) {
    return this._session.onTools
      ? toolsHook(this._session, reading.text, reading.frame, (answered) => this._toolsAnswer(reading, answered))
      : null;
  }

  _toolsAnswer(reading, answered) {
    const session = this._session;
    if (!answered) return null;
    session.counts.tools_answered += 1;
    session.state.noteAgentReply(masked(answered));
    return new TurnResult(reading.turnId, reading.verdict.route, {
      text: answered, needsModel: false, frame: reading.frame, verdict: reading.verdict, reason: TOOLS_REASON,
    });
  }
}

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

const SAVED_COUNT = "saved";
const NOT_SHARED = new Verdict("NotShared", "not a shared question the model answered", [], OUTCOME.NOT_SHARED);

/**
 * check(): the agent's reply is noted in the chat's state (names masked unless the question was
 * shared); only the model's answer to a shared question may be saved, and only past the save rules.
 * write(): agent.learn(), waited for no longer than twice the latency budget (BoundedWriter, as voice;
 * waited for without a budget; a failed write is `report`'s refusal), then the question it was saved
 * for is kept. `session` is read live
 * (state, counts, agent, instructions, latencyBudgetMs, promptKey()).
 */
class ChatSaving {
  constructor(session, { saveRules, writer, questionRecords, report }) {
    this._session = session;
    this._report = report;
    this._saveRules = saveRules;
    this._writer = writer;
    this._questionRecords = questionRecords;
  }

  check(answered) {
    const { result, answer } = answered;
    const kept = result.route === SHARED ? answer : masked(answer);
    this._session.state.noteAgentReply(kept, answered.mentions, answered.task);
    if (result.route !== SHARED || result.text !== null || !result.verdict) return new Checked(answered, NOT_SHARED);
    const why = this.saveCheck(answer, result.verdict, result.frame, answered.private);
    if (why) return new Checked(answered, new Verdict("SaveCheck", why, [SAVE_REFUSED], because(OUTCOME.REFUSED, why)));
    return new Checked(answered);
  }

  async write(answered) {
    const { verdict } = answered.result;
    const answer = answered.answer;
    const learn = () => this._session.agent.learn(verdict.key, answer, {
      ttl: verdict.ttl ?? undefined, ...(verdict.segment ? { segment: verdict.segment } : {}),
    });
    const written = await this._writer.writeWithin(learn, this._session.latencyBudgetMs);
    if (written.refused) return this._report.refused(written.error);
    if (!written.written) return written.objection.outcome;
    this._session.counts[SAVED_COUNT] += 1;
    this._questionRecords.keep(verdict.key, answer, verdict.ttl ?? null);
    return OUTCOME.SAVED;
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null, isPrivate = false) {
    const session = this._session;
    const chatAnswer = new ChatAnswer(String(answer || "").split(/\s+/).filter(Boolean).join(" "), verdict, frame,
      session.state, { instructions: session.instructions, promptKey: session.promptKey(), private: isPrivate });
    const objection = this._saveRules.firstObjection(chatAnswer);
    return objection ? objection.reason : null;
  }
}

module.exports = { ChatAnswers, ChatReport, ChatSaving, ChatTurns, SAVE_REFUSED, eventHook };
