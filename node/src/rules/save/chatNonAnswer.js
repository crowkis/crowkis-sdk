"use strict";

// The ChatNonAnswer rule (stage 3, save; Chat, "non_answer").

const { Verdict } = require("../../turns/verdict.js");
const { isNonAnswer } = require("../../understanding/wordRules/index.js");

/** An answer that asks back or does not answer is not saved. */
class ChatNonAnswer {
  get name() {
    return "ChatNonAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!isNonAnswer(answer.text)) return null;
    return new Verdict(this.name, "non_answer");
  }
}

module.exports = { ChatNonAnswer };
