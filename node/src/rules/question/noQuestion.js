"use strict";

// The NoQuestion rule (stage 1, question; Chat, V3).

const { Verdict } = require("../../turns/verdict.js");

/** A frame with no stand-alone question has nothing to look up or share. */
class NoQuestion {
  get name() {
    return "NoQuestion";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.question) return null;
    return new Verdict(this.name, "V3_no_question");
  }
}

module.exports = { NoQuestion };
