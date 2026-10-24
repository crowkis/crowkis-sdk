"use strict";

// The VoiceActionClaim rule (stage 3, save; voice with an understander).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");
const { ACTION_CLAIM } = require("../../understanding/answerPatterns.js");

/**
 * Chat's ActionClaim on voice (v4): an answer saying something was done for this caller ("I have
 * cancelled your order") is not shared.
 */
class VoiceActionClaim {
  get name() {
    return "VoiceActionClaim";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!ACTION_CLAIM.test(answer.answer || "")) return null;
    return new Verdict(this.name, "kept to this call: the answer says something was done for this caller",
      [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

module.exports = { VoiceActionClaim };
