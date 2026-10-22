"use strict";

// The UncertainFrame rule (stage 1, question; Chat, V2).

const { Verdict } = require("../../turns/verdict.js");

/** The understanding model abstained, or is less sure than the confidence floor. */
class UncertainFrame {
  constructor({ confidenceFloor }) {
    this._confidenceFloor = confidenceFloor;
  }

  get name() {
    return "UncertainFrame";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.frame.abstain || turn.frame.confidence < this._confidenceFloor)) return null;
    return new Verdict(this.name, "V2_uncertain");
  }
}

module.exports = { UncertainFrame };
