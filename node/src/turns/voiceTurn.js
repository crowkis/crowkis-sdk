"use strict";

/**
 * What the caller said in one turn, the call it belongs to, and how it was understood: `reading`
 * is the classifier's (personal, a follow-up) and `rewritten` the rewriter's stand-alone
 * question, or null to key the turn on the caller's words.
 */
class VoiceTurn {
  constructor(said, call, reading, rewritten = null) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.call = call;
    this.reading = reading;
    this.rewritten = rewritten;
    this._read = new Map();
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** Too few words to match on meaning. */
  get isShort() {
    return this._once("isShort", () => this.text.split(/\s+/).length < this.call.minWords);
  }

  /** About the caller's own records, or otherwise never shared. */
  get isPersonal() {
    return this.reading.isPersonal || this.call.isPersonal(this.text);
  }

  /** Only means something next to the turn before it. */
  get isContextDependent() {
    return this.reading.isContextDependent;
  }

  /** The cache key: the rewritten question, else the caller's words or the chain a follow-up leans on; null without one. */
  get key() {
    return this._once("key", () => (this.rewritten !== null ? this.rewritten : this.call.contextKey(this.said, this.text)));
  }
}

module.exports = { VoiceTurn };
