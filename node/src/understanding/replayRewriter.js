"use strict";

const { ReplayUnderstander } = require("./understanders.js");
const { FrameReading } = require("./frameReading.js");

/**
 * Keys a turn on a verified question only when the turn repeats it word for word (case, punctuation
 * and spacing aside); anything else keeps the caller's words. It needs no model and cannot be talked
 * into a different question.
 */
class ReplayRewriter {
  constructor(known = {}) {
    this._replay = new ReplayUnderstander(known);
  }

  /** Recognise `turn` (and `question` itself) as the verified `question` from now on. */
  remember(turn, question, questionType = "other") {
    this._replay.remember(turn, question, questionType);
  }

  /** The verified question this turn repeats, or null (also for a turn read as personal). */
  rewrite(text, reading) {
    if (reading.isPersonal) return null;
    return new FrameReading(this._replay.understand(text)).question;
  }
}

module.exports = { ReplayRewriter };
