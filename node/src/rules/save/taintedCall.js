"use strict";

// The TaintedCall rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

/** Once the caller told the call something an answer may depend on, nothing more is shared. */
class TaintedCall {
  get name() {
    return "TaintedCall";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.call.tainted) return null;
    return new Verdict(this.name, "kept to this call: the caller told it something the answer may depend on",
      [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

module.exports = { TaintedCall };
