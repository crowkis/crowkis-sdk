"use strict";

const { masked, norm } = require("../understanding/chatDetails.js");
const { AGENT, FILLER, PERSONAL, TOOLS, URGENT } = require("./routes.js");
const { TurnResult } = require("./turnResult.js");

const SHARING_OFF = "off";
const URGENT_SCRIPT_REASON = "urgent script";
const TOOLS_REASON = "answered by the business's tools";

/**
 * What a chat answers without the cache or the model, as TurnCore's EarlyAnswers. Before a turn is
 * read: an empty turn goes to the agent, a registered filler answers it, and with sharing off the
 * agent answers everything. After the check: the app's `onUrgent` hook runs on an urgent turn and its
 * `urgentReply` answers it; `onTools` may answer a personal or live turn. None of these is ever
 * cached; a hook that fails never ends the chat. `session` is read live (state, counts, mode, fillers,
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
    return this._session.onUrgent ? this._urgentAfterHook(reading) : this._urgentReply(reading);
  }

  async _urgentAfterHook(reading) {
    try { await this._session.onUrgent(reading.text, reading.frame); } catch { /* the hook must not take the call down */ }
    return this._urgentReply(reading);
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
    return this._session.onTools ? this._toolsAnswer(reading) : null;
  }

  async _toolsAnswer(reading) {
    const session = this._session;
    let answered = null;
    try { answered = await session.onTools(reading.text, reading.frame); } catch { answered = null; /* a failing tool means the model answers */ }
    if (!answered) return null;
    session.counts.tools_answered += 1;
    session.state.noteAgentReply(masked(answered));
    return new TurnResult(reading.turnId, reading.verdict.route, {
      text: answered, needsModel: false, frame: reading.frame, verdict: reading.verdict, reason: TOOLS_REASON,
    });
  }
}

module.exports = { ChatAnswers };
