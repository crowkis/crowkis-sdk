"use strict";

// The NonAnswer rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");

const NON_ANSWER = "non_answer";

/** An answer that asks back or does not answer is not saved. */
class NonAnswer {
  get name() {
    return "NonAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.isNonAnswer) return null;
    return new Verdict(this.name, "not saved: the answer asks back or does not answer", ["notShareable"], NON_ANSWER);
  }
}

module.exports = { NonAnswer };
