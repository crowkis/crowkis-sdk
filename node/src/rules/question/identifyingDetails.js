"use strict";

// The IdentifyingDetails rule (stage 1, question; Chat, V5).

const { Verdict } = require("../../turns/verdict.js");
const { looksIdentifying } = require("../../understanding/frameWords.js");

/** An identifying entity, an email, a phone number or an ID-like digit run never enters a key. */
class IdentifyingDetails {
  get name() {
    return "IdentifyingDetails";
  }

  get floor() {
    return true;
  }

  check(turn) {
    const question = turn.question;
    const low = question.toLowerCase();
    if (!(turn.frame.identifyingTexts.some((t) => low.includes(t.toLowerCase())) || looksIdentifying(question))) return null;
    return new Verdict(this.name, "V5_identifying");
  }
}

module.exports = { IdentifyingDetails };
