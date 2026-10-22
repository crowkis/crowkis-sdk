"use strict";

// The ChatPromptDetails rule (stage 3, save; Chat, "prompt_detail").

const { Verdict } = require("../../turns/verdict.js");
const { repeatsPromptDetails } = require("../../understanding/wordRules/index.js");

/** An answer repeating a detail the system prompt gives about this user ("Hi Asha!") is right for this user only. */
class ChatPromptDetails {
  get name() {
    return "ChatPromptDetails";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.instructions || !repeatsPromptDetails(answer.text, answer.verdict.question || "", answer.instructions, answer.promptKey)) {
      return null;
    }
    return new Verdict(this.name, "prompt_detail");
  }
}

module.exports = { ChatPromptDetails };
