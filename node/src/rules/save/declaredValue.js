"use strict";

// The DeclaredValue rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");
const { leaks } = require("../../understanding/wordRules.js");

const PRIVATE = "private";

/** An answer holding a value declared for this call is never shared. */
class DeclaredValue {
  get name() {
    return "DeclaredValue";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!leaks(answer.answer, answer.call.values)) return null;
    return new Verdict(this.name, "kept to this call: the answer contains a value declared for this call",
      ["notShareable"], PRIVATE);
  }
}

module.exports = { DeclaredValue };
