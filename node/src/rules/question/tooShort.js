"use strict";

// The TooShort rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");

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

module.exports = { TooShort };
