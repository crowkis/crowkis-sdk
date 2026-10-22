"use strict";

const { isPersonal, privateChain } = require("./wordRules/index.js");

/**
 * The caller turns of one call that the classifier read as personal. A turn is personal when its
 * reading or the word rules say so, so a plugged-in classifier can only make a call more private,
 * never less. Kept per call: what decide() read is what record() and later follow-ups check.
 */
class PersonalReadings {
  constructor() {
    this._readPersonal = new Set();
  }

  /** Remember a turn's reading (the trimmed words the classifier read). */
  note(text, reading) {
    if (reading.isPersonal) this._readPersonal.add(text.trim());
  }

  /** The turn is about the caller's own records, by its reading or by the word rules. */
  isPersonal(text) {
    const trimmed = typeof text === "string" ? text.trim() : "";
    return this._readPersonal.has(trimmed) || isPersonal(trimmed);
  }

  /** A follow-up chain is private by the word rules, or when any turn of it was read as personal. */
  chainIsPrivate(chain, minWords) {
    return privateChain(chain, minWords) || chain.some((turn) => this.isPersonal(turn));
  }
}

module.exports = { PersonalReadings };
