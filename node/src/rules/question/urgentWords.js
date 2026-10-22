"use strict";

// The UrgentWords rule (stage 1, question; Chat, "V1_urgent_fixed", checked once the rule checker would share).

const { Verdict } = require("../../turns/verdict.js");
const { URGENT } = require("../../turns/routes.js");
const { tellsAboutCaller, urgent, wordsOf } = require("../../understanding/wordRules/index.js");

/**
 * A turn about the caller that the fixed urgent words catch takes the urgent route, whatever the
 * model said: an emergency is never left to the model alone.
 */
class UrgentWords {
  get name() {
    return "UrgentWords";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!(tellsAboutCaller(turn.text) && urgent(wordsOf(turn.text)))) return null;
    return new Verdict(this.name, "V1_urgent_fixed", [], null, URGENT);
  }
}

module.exports = { UrgentWords };
