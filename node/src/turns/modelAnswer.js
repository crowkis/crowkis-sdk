"use strict";

const { isNonAnswer, isPersonal } = require("../understanding/wordRules.js");

/**
 * What the model said to a turn, with what is known about that turn when it is recorded.
 * `key` is the turn's cache key, worked out before the turn joined the transcript. `private`
 * means the answer was built from a tool's result; `instructions` is the system prompt the
 * model read; `cacheable` is whether decide() let the answer be shared.
 */
class ModelAnswer {
  constructor(said, answer, key, call, { private: keep = false, instructions = null, cacheable = false } = {}) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.answer = answer;
    this.key = key;
    this.call = call;
    this.private = keep;
    this.instructions = instructions;
    this.cacheable = cacheable;
    this._read = new Map();
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** The turn was about the caller's own records. */
  get isPersonal() {
    return this._once("isPersonal", () => isPersonal(this.text));
  }

  /** The answer asks back or does not answer. */
  get isNonAnswer() {
    return this._once("isNonAnswer", () => isNonAnswer(this.answer));
  }
}

module.exports = { ModelAnswer };
