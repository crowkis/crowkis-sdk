"use strict";

// The DeclaredValue rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { leaks } = require("../../understanding/wordRules/index.js");
const { COUNTER } = require("../../runtime/stats.js");

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
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

module.exports = { DeclaredValue };
