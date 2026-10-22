"use strict";

// The QuestionNamesCaller rule (stage 1, question; Chat, "V5_private_word", checked once the rule checker would share).

const { Verdict } = require("../../turns/verdict.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");

/** The shared question says what named the caller earlier ("for sarah"). */
class QuestionNamesCaller {
  get name() {
    return "QuestionNamesCaller";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!wordsOf(turn.question || "").some((w) => turn.state.isName(w))) return null;
    return new Verdict(this.name, "V5_private_word");
  }
}

module.exports = { QuestionNamesCaller };
