"use strict";

// The CutOff rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { unfinished } = require("../../understanding/wordRules/index.js");
const { COUNTER } = require("../../runtime/stats.js");

/**
 * A cut-off question ("do you deliver on") is close in meaning to a full one but asks something
 * else: never served a stored answer, never stored.
 */
class CutOff {
  get name() {
    return "CutOff";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!unfinished(turn.text)) return null;
    return new Verdict(this.name, "the turn was cut off mid-question", [COUNTER.REFUSED_SHORT]);
  }
}

module.exports = { CutOff };
