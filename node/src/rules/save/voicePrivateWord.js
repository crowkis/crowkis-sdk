"use strict";

// The VoicePrivateWord rule (stage 3, save; voice with an understander).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");

/**
 * Chat's PrivateWord on voice (v4): a word that identified the caller in a turn kept private ("Sarah",
 * "55512") is never in a shared answer, unless the shared question itself has it.
 */
class VoicePrivateWord {
  get name() {
    return "VoicePrivateWord";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const asked = new Set(wordsOf(answer.key || ""));
    const privateWords = answer.call.privateWords();
    if (!wordsOf(answer.answer).some((w) => !asked.has(w) && privateWords.has(w))) return null;
    return new Verdict(this.name, "kept to this call: the answer holds a word that identified this caller",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

module.exports = { VoicePrivateWord };
