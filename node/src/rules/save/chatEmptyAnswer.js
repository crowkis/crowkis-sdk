"use strict";

// The ChatEmptyAnswer rule (stage 3, save; Chat, "empty").

const { Verdict } = require("../../turns/verdict.js");

/** An empty answer has nothing to save. */
class ChatEmptyAnswer {
  get name() {
    return "ChatEmptyAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.text) return null;
    return new Verdict(this.name, "empty");
  }
}

module.exports = { ChatEmptyAnswer };
