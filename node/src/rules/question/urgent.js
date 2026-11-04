"use strict";

// Stage 1 rules (question): an urgent turn.

const { Verdict } = require("../../turns/values.js");
const { URGENT } = require("../../turns/results.js");
const { tellsAboutCaller, urgent, wordsOf } = require("../../understanding/wordRules/index.js");

// The UrgentTurn rule (stage 1, question; Chat, V1).
/** An urgent turn (an emergency, a crisis) takes the urgent route and is never shared. */
class UrgentTurn {
  get name() {
    return "UrgentTurn";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!turn.frame.urgent) return null;
    return new Verdict(this.name, "V1_urgent", [], null, URGENT);
  }
}

// The UrgentWords rule (stage 1, question; Chat, "V1_urgent_fixed", checked once the rule checker would share).
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

module.exports = { UrgentTurn, UrgentWords };
