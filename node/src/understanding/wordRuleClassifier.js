"use strict";

const { isContextDependent } = require("./wordRules/followUp.js");
const { isPersonal } = require("./wordRules/personal.js");

/** What the word rules make of one turn's words. Each reading is worked out once, when a rule first needs it. */
class WordReading {
  constructor(text) {
    this.text = text;
    this._read = new Map();
  }

  /** The word rules make no frame. */
  get frame() {
    return null;
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** About the caller's own records, or otherwise never shared. */
  get isPersonal() {
    return this._once("isPersonal", () => isPersonal(this.text));
  }

  /** Only means something next to the turn before it. */
  get isContextDependent() {
    return this._once("isContextDependent", () => isContextDependent(this.text));
  }
}

/**
 * The classifier a voice session uses when no understander is plugged in: the fixed word rules,
 * so nothing changes without opt-in.
 */
class WordRuleClassifier {
  classify(text, facts = []) {
    return new WordReading(text);
  }
}

module.exports = { WordReading, WordRuleClassifier };
