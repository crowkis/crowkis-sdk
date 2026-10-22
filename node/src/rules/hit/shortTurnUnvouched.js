"use strict";

// The ShortTurnUnvouched rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

const SHORT_TURN_REASON =
  "a short turn is only answered from cache once the answer has been " +
  "judged to stand on its own, and this one has not";

/** A short turn is served only an exact match the server's decision engine has vouched for. */
class ShortTurnUnvouched {
  get name() {
    return "ShortTurnUnvouched";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!cached.turn.isShort || (cached.hit.vouched && cached.hit.exact)) return null;
    return new Verdict(this.name, SHORT_TURN_REASON, [COUNTER.INFERRED]);
  }
}

module.exports = { ShortTurnUnvouched };
