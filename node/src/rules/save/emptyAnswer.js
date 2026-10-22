"use strict";

// The EmptyAnswer rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");

const NON_ANSWER = "non_answer";

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
    return new Verdict(this.name, "the model returned an empty answer", ["emptyAnswers"], NON_ANSWER);
  }
}

module.exports = { EmptyAnswer };
