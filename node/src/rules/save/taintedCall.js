"use strict";

// The TaintedCall rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");

const KEPT = "kept";

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
      ["notShareable"], KEPT);
  }
}

module.exports = { TaintedCall };
