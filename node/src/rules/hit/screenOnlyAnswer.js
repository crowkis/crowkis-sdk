"use strict";

// The ScreenOnlyAnswer rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { speakable } = require("../../understanding/wordRules/index.js");

const SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)";

/** An answer written for a screen (a link, code or markup) is not spoken. */
class ScreenOnlyAnswer {
  get name() {
    return "ScreenOnlyAnswer";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (speakable(cached.answer)) return null;
    return new Verdict(this.name, SCREEN_REASON, ["unspeakable", "inferred"]);
  }
}

module.exports = { ScreenOnlyAnswer };
