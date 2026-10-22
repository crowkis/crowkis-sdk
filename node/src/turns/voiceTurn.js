"use strict";

const { isContextDependent, isPersonal } = require("../understanding/wordRules.js");

/**
 * What the caller said in one turn, the call it belongs to, and what the word rules make of it.
 * Each reading is worked out once, when a rule first needs it.
 */
class VoiceTurn {
  constructor(said, call) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.call = call;
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
    return this._once("isPersonal", () => isPersonal(this.text));
  }

  /** Only means something next to the turn before it. */
  get isContextDependent() {
    return this._once("isContextDependent", () => isContextDependent(this.text));
  }

  /** The cache key: the caller's words, or the chain a follow-up leans on; null without one. */
  get key() {
    return this._once("key", () => this.call.contextKey(this.said, this.text));
  }
}

module.exports = { VoiceTurn };
