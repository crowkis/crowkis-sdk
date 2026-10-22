"use strict";

// The EmptyTurn rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

/** An empty transcript goes to the model. */
class EmptyTurn {
  get name() {
    return "EmptyTurn";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.text) return null;
    return new Verdict(this.name, "empty transcript", [COUNTER.REFUSED_SHORT]);
  }
}

module.exports = { EmptyTurn };
