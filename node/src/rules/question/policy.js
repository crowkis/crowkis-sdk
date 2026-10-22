"use strict";

// Question rules about turns too short or too broken to match on meaning.

const { Verdict } = require("../../turns/verdict.js");
const { unfinished } = require("../../understanding/wordRules.js");

/**
 * A turn too short to match on meaning ("thank you") is not looked up, unless short turns are
 * on and the server's decision engine vouches for what it caches.
 */
class TooShort {
  get name() {
    return "TooShort";
  }

  get floor() {
    return false;
  }

  // Asks the server only when it must (a short turn, short turns on): then a promise.
  check(turn) {
    if (!turn.isShort) return null;
    const verdict = new Verdict(this.name, "transcript too short to match safely", ["refusedShort"]);
    if (!turn.call.shortTurns) return verdict;
    return Promise.resolve(turn.call.engineVouches()).then((vouches) => (vouches ? null : verdict));
  }
}

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
    return new Verdict(this.name, "the turn was cut off mid-question", ["refusedShort"]);
  }
}

module.exports = { CutOff, TooShort };
