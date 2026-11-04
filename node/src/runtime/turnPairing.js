"use strict";

const { Checked } = require("../turns/checked.js");
const { OUTCOME } = require("../turns/outcome.js");
const { Verdict } = require("../turns/verdict.js");

const INTERRUPTED = new Verdict("Interrupted", "the caller moved on before this answer was complete", [], OUTCOME.INTERRUPTED);
const NOTHING_SHARED = Object.freeze([0, false]);

/**
 * Pairs each model answer with the turn it answers, so an answer to a turn the caller talked over,
 * or to one before the latest, is never saved or lands on later words. Every decided turn gets a
 * number (begin); the open turn can be cancelled (barge-in); a turn's answer may be shared only if
 * the latest decision for that same turn said so (offer) and nothing moved on before it is recorded
 * (settleTurn). Also TurnCore's Pairing for a voice call (`session`, read live for its transcript): open()
 * numbers a turn and opens it where it starts in the transcript; settle() makes an answer to a turn the caller
 * moved on from `Interrupted`, and a paired answer carries whether decide() let it be shared. Python's twin also holds the lock recording runs under; Node runs one step at a time.
 */
class TurnPairing {
  constructor({ session } = {}) {
    this._session = session;
    this.turn = 0;
    this.isOpen = false;
    this.cancelled = false;
    this.mark = 0;
    this._shareable = NOTHING_SHARED;
  }

  /** Number the next decided turn. */
  begin() {
    this.turn += 1;
    return this.turn;
  }

  open() {
    const turn = this.begin();
    this.start(this._session.transcript.length);
    return turn;
  }

  settle(answered) {
    const settled = this.settleTurn(answered.turn);
    if (!settled) return new Checked(answered, INTERRUPTED);
    return new Checked(answered.paired(settled[1]));
  }

  /** The turn being decided is open; `mark` is where it starts in the transcript. */
  start(mark) {
    this.mark = mark;
    this.isOpen = true;
    this.cancelled = false;
  }

  /** What decide() said about sharing `turn`'s answer; a newer turn's word is never overwritten. */
  offer(turn, cacheable) {
    if (turn === this.turn) this._shareable = [turn, cacheable];
  }

  /** Barge-in: the open turn is closed and trim(mark) drops it from the transcript. */
  cancel(trim) {
    if (!this.isOpen) return false;
    this.isOpen = false;
    this.cancelled = true;
    trim(this.mark);
    return true;
  }

  /** The caller talked over `turn`, or a newer turn has been decided. */
  movedOn(turn) {
    return this.cancelled || turn !== this.turn;
  }

  /**
   * The answer to `turn` (null or undefined: the latest) arrived. null when the caller moved on;
   * otherwise [that turn, whether decide() let its answer be shared]. Closes the turn.
   */
  settleTurn(turn) {
    const given = turn !== undefined && turn !== null;
    if (this.cancelled || (given && turn !== this.turn)) return null;
    this.isOpen = false;
    const expected = given ? turn : this.turn;
    const shareable = this._shareable;
    this._shareable = NOTHING_SHARED;
    return [expected, shareable[1] && shareable[0] === expected];
  }

  /** A turn kept to the call without a decision: forget what decide() offered. true when it had offered to share. */
  dropShareable() {
    const offered = this._shareable[1];
    this._shareable = NOTHING_SHARED;
    return offered;
  }
}

module.exports = { TurnPairing };
