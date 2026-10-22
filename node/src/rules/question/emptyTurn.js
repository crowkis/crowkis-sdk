"use strict";

// The EmptyTurn rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");

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
    return new Verdict(this.name, "empty transcript", ["refusedShort"]);
  }
}

module.exports = { EmptyTurn };
