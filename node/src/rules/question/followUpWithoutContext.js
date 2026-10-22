"use strict";

// The FollowUpWithoutContext rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

const NO_KEY_REASON =
  "the utterance only has meaning against an earlier turn and this call " +
  "has none, so no cache key can be built for it";

/** A follow-up ("and what about that") with no earlier turn to lean on has no cache key. */
class FollowUpWithoutContext {
  get name() {
    return "FollowUpWithoutContext";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.key !== null) return null;
    return new Verdict(this.name, NO_KEY_REASON, [COUNTER.INFERRED]);
  }
}

module.exports = { FollowUpWithoutContext };
