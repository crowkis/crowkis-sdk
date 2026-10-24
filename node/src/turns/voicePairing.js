"use strict";

const { Checked } = require("./checked.js");
const { Verdict } = require("./verdict.js");

const INTERRUPTED = new Verdict("Interrupted", "the caller moved on before this answer was complete", [], "interrupted");

/**
 * Adapter: a call's TurnPairing as TurnCore's Pairing. Every decided turn gets the next number and
 * opens where it starts in the transcript (a barge-in trims back to there); an answer to a turn the
 * caller moved on from is `Interrupted`; a paired answer carries whether decide() let it be shared.
 * `session` is read live for its transcript.
 */
class VoicePairing {
  /**
   * @param {import("../runtime/turnPairing.js").TurnPairing} pairing
   * @param {{ transcript: object[] }} session
   */
  constructor(pairing, session) {
    this._pairing = pairing;
    this._session = session;
  }

  open() {
    const turn = this._pairing.begin();
    this._pairing.start(this._session.transcript.length);
    return turn;
  }

  settle(answered) {
    const settled = this._pairing.settle(answered.turn);
    if (!settled) return new Checked(answered, INTERRUPTED);
    return new Checked(answered.paired(settled[1]));
  }
}

module.exports = { INTERRUPTED, VoicePairing };
