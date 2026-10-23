"use strict";

const { isContextDependent, isPersonal, privateChain, setsContext } = require("./wordRules/index.js");
const { privateWords } = require("./chatDetails.js");

// The newest facts and stated turns a call keeps (as Chat's CallState does).
const MAX_FACTS = 12;
const MAX_STATED = 12;

/**
 * What the classifier and rewriter made of each caller turn of one call, kept so that record() and
 * later follow-ups read the turn the way decide() did.
 *
 * A turn is personal, or a follow-up, when its reading or the word rules say so, so a plugged-in
 * classifier can only make a call more private, never less. A rewritten turn's answer is saved under
 * the question it was looked up with; each turn sets or clears its rewrite, so an earlier turn's never
 * keys a later one. It also keeps what the caller told the call: the stated turns (never sent
 * anywhere; StatedFacts checks them) and the de-identified facts the model's frames remembered (the
 * classifier reads them).
 */
class CallReadings {
  constructor() {
    this._readPersonal = new Set();
    this._readFollowUp = new Set();
    this._rewritten = new Map();
    this._stated = [];
    this._facts = [];
    this._privateWords = new Set();
  }

  /** Remember a turn's reading and rewrite (keyed by the trimmed words the classifier read). */
  note(text, reading, rewritten) {
    const trimmed = text.trim();
    if (reading.isPersonal) this._readPersonal.add(trimmed);
    if (this.isPersonal(trimmed)) for (const w of privateWords(trimmed, reading.frame || null)) this._privateWords.add(w);
    if (reading.isContextDependent) this._readFollowUp.add(trimmed);
    if (rewritten === null || rewritten === undefined) this._rewritten.delete(trimmed);
    else this._rewritten.set(trimmed, rewritten);
    if (setsContext(trimmed)) this._stated = [...this._stated, trimmed].slice(-MAX_STATED);
    const frame = reading.frame || null;
    for (const entity of frame ? frame.memorable : []) {
      const fact = `${entity.type}: ${entity.text}`;
      this._facts = [...this._facts.filter((f) => f !== fact), fact].slice(-MAX_FACTS);
    }
  }

  /** Read this turn as personal from now on (a rule kept it private). */
  markPrivate(text) {
    this._readPersonal.add(typeof text === "string" ? text.trim() : "");
    for (const w of privateWords(typeof text === "string" ? text : "")) this._privateWords.add(w);
  }

  /** Every word that may identify the caller in the turns kept private, lower case. Never sent anywhere. */
  privateWords() {
    return new Set(this._privateWords);
  }

  /** The turns in which the caller told the call something, oldest first. */
  get stated() {
    return [...this._stated];
  }

  /** The call's de-identified facts ("condition: car hit"), as the classifier reads them. */
  get facts() {
    return [...this._facts];
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
