"use strict";

// The NotGeneral rule (stage 1, question; Chat, V3).

const { Verdict } = require("../../turns/verdict.js");

/** A turn that is not a general question about no one in particular is not shared. */
class NotGeneral {
  get name() {
    return "NotGeneral";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (turn.frame.kind === "general" && turn.frame.subject === "none") return null;
    return new Verdict(this.name, "V3_not_general");
  }
}

module.exports = { NotGeneral };
