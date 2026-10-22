"use strict";

// The IdentifyingAnswer rule (stage 3, save; Chat, "identifying").

const { Verdict } = require("../../turns/verdict.js");
const { EMAIL, LONG_DIGITS } = require("../../understanding/answerPatterns.js");

/** An answer holding an email, a long digit run, or a detail the frame tagged as identifying is never shared. */
class IdentifyingAnswer {
  get name() {
    return "IdentifyingAnswer";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const t = answer.text;
    const tagged = Boolean(answer.frame) && answer.frame.identifyingTexts.some((x) => t.toLowerCase().includes(x.toLowerCase()));
    if (!(EMAIL.test(t) || LONG_DIGITS.test(t) || tagged)) return null;
    return new Verdict(this.name, "identifying");
  }
}

module.exports = { IdentifyingAnswer };
