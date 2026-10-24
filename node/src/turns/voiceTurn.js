"use strict";

const { CONTEXT_BOUND_THRESHOLD } = require("../understanding/wordRules/index.js");

/**
 * What the caller said in one turn, the call it belongs to, and how it was understood: `reading`
 * is the classifier's (personal, a follow-up) and `rewritten` the rewriter's stand-alone
 * question, or null to key the turn on the caller's words. `segment` is where the call's answers
 * are looked up (null: no segment, as before); `number` is the turn's number in the call.
 */
class VoiceTurn {
  constructor(said, call, reading, rewritten = null, { segment = null, number = 0 } = {}) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.call = call;
    this.reading = reading;
    this.rewritten = rewritten;
    this.segment = segment;
    this.number = number;
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
    return this.reading.isContextDependent || this.call.isContextDependent(this.text);
  }

  /** The model's frame of the turn, or null (the word rules make none). */
  get frame() {
    return this.reading.frame ?? null;
  }

  /** The cache key: the rewritten question, else the caller's words or the chain a follow-up leans on; null without one. */
  get key() {
    return this._once("key", () => (this.rewritten !== null ? this.rewritten : this.call.contextKey(this.said, this.text)));
  }

  /**
   * What the lookup sends besides the key: a template lookup for a personal turn, the stricter
   * threshold for a follow-up or a short turn, and the segment only when there is one (with an
   * understander, kb=<version>): the default lookup is as it was.
   */
  get lookupOptions() {
    return {
      template: this.isPersonal,
      threshold: this.isContextDependent || this.isShort ? CONTEXT_BOUND_THRESHOLD : undefined,
      ...(this.segment ? { segment: this.segment } : {}),
    };
  }
}

module.exports = { VoiceTurn };
