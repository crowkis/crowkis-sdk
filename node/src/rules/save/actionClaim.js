"use strict";

// The ActionClaim rule (stage 3, save; Chat, "action_claim").

const { Verdict } = require("../../turns/verdict.js");
const { ACTION_CLAIM } = require("../../understanding/answerPatterns.js");

/** An answer saying something was done for this user ("I have cancelled your order") is not shared. */
class ActionClaim {
  get name() {
    return "ActionClaim";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!ACTION_CLAIM.test(answer.text)) return null;
    return new Verdict(this.name, "action_claim");
  }
}

module.exports = { ActionClaim };
