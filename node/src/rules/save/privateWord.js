"use strict";

// The PrivateWord rule (stage 3, save; Chat, "private_word").

const { Verdict } = require("../../turns/verdict.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");

/**
 * A word that identified the user in a turn that was not shared ("Sarah", "55512") is never in a
 * shared answer, unless the shared question itself has it.
 */
class PrivateWord {
  get name() {
    return "PrivateWord";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const asked = new Set(wordsOf(answer.verdict.question || ""));
    if (!wordsOf(answer.text).some((w) => !asked.has(w) && answer.state.isPrivate(w))) return null;
    return new Verdict(this.name, "private_word");
  }
}

module.exports = { PrivateWord };
