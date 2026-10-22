"use strict";

// The NoKey rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");

const NOT_SAVED = "not_saved";

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
    return new Verdict(this.name, "a follow-up with no earlier turn to key it on", [], NOT_SAVED);
  }
}

module.exports = { NoKey };
