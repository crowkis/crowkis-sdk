"use strict";

// The CommitmentRewording rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COMMITMENT_POLICIES } = require("./commitmentPolicy.js");
const { COUNTER } = require("../../runtime/stats.js");

/**
 * A commitment (a price, a refund, a policy) is spoken only as the call's `commitments` setting
 * allows: by default, only for the exact same question.
 */
class CommitmentRewording {
  get name() {
    return "CommitmentRewording";
  }

  get floor() {
    return false;
  }

  check(cached) {
    const commitments = cached.turn.call.commitments;
    const { hit } = cached;
    if (!(hit.commitment || hit.unjudged) || COMMITMENT_POLICIES[commitments](hit)) return null;
    const reason =
      (hit.commitment
        ? "the cached answer is a commitment (a price, a refund, a policy)"
        : "the cached answer has not been judged yet, so it may be a commitment") +
      ` and commitments="${commitments}" does not allow speaking this match`;
    return new Verdict(this.name, reason, [COUNTER.HELD_COMMITMENTS, COUNTER.INFERRED]);
  }
}

module.exports = { CommitmentRewording };
