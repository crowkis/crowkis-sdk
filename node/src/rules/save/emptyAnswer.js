"use strict";

// The EmptyAnswer rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

/** A model that said nothing has nothing to save. */
class EmptyAnswer {
  get name() {
    return "EmptyAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (typeof answer.answer === "string" && answer.answer.trim()) return null;
    return new Verdict(this.name, "the model returned an empty answer", [COUNTER.EMPTY_ANSWERS], OUTCOME.NON_ANSWER);
  }
}

module.exports = { EmptyAnswer };
