"use strict";

const { Checked } = require("./checked.js");
const { Verdict } = require("./verdict.js");

const CANCELLED = "cancelled";
const STALE = "stale";
const CANCELLED_VERDICT = new Verdict("Cancelled", "the user talked over this turn", [CANCELLED], CANCELLED);
// An older turn finishing after a newer one started: never saved.
const STALE_VERDICT = new Verdict("Stale", "a newer turn awaits the answer", [], STALE);

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

module.exports = { ChatTurns };
