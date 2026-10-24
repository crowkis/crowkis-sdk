"use strict";

// The NoKey rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");

/** A follow-up with no earlier turn to key it on cannot be saved. */
class NoKey {
  get name() {
    return "NoKey";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.key !== null) return null;
    return new Verdict(this.name, "a follow-up with no earlier turn to key it on", [], OUTCOME.NOT_SAVED);
  }
}

module.exports = { NoKey };
