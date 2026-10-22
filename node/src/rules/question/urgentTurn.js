"use strict";

// The UrgentTurn rule (stage 1, question; Chat, V1).

const { Verdict } = require("../../turns/verdict.js");
const { URGENT } = require("../../turns/routes.js");

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

module.exports = { UrgentTurn };
