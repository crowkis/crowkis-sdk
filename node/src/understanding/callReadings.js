"use strict";

const { isContextDependent, isPersonal, privateChain } = require("./wordRules/index.js");

/**
 * What the classifier and rewriter made of each caller turn of one call, kept so that record() and
 * later follow-ups read the turn the way decide() did.
 *
 * A turn is personal, or a follow-up, when its reading or the word rules say so, so a plugged-in
 * classifier can only make a call more private, never less. A rewritten turn's answer is saved under
 * the question it was looked up with; each turn sets or clears its rewrite, so an earlier turn's never
 * keys a later one.
 */
class CallReadings {
  constructor() {
    this._readPersonal = new Set();
    this._readFollowUp = new Set();
    this._rewritten = new Map();
  }

  /** Remember a turn's reading and rewrite (keyed by the trimmed words the classifier read). */
  note(text, reading, rewritten) {
    const trimmed = text.trim();
    if (reading.isPersonal) this._readPersonal.add(trimmed);
    if (reading.isContextDependent) this._readFollowUp.add(trimmed);
    if (rewritten === null || rewritten === undefined) this._rewritten.delete(trimmed);
    else this._rewritten.set(trimmed, rewritten);
  }

  /** The turn is about the caller's own records, by its reading or by the word rules. */
  isPersonal(text) {
    const trimmed = typeof text === "string" ? text.trim() : "";
    return this._readPersonal.has(trimmed) || isPersonal(trimmed);
  }

  /** The turn only means something next to the one before, by its reading or by the word rules. */
  isContextDependent(text) {
    const trimmed = typeof text === "string" ? text.trim() : "";
    return this._readFollowUp.has(trimmed) || isContextDependent(trimmed);
  }

  /** A follow-up chain is private by the word rules, or when any turn of it was read as personal. */
  chainIsPrivate(chain, minWords) {
    return privateChain(chain, minWords) || chain.some((turn) => this.isPersonal(turn));
  }

  /** The stand-alone question this turn was looked up with, or null when it was not rewritten. */
  rewritten(text) {
    const trimmed = typeof text === "string" ? text.trim() : "";
    return this._rewritten.has(trimmed) ? this._rewritten.get(trimmed) : null;
  }
}

module.exports = { CallReadings };
