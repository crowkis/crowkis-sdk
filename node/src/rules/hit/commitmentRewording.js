"use strict";

// The CommitmentRewording rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COMMITMENTS } = require("../../understanding/wordRules/index.js");

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
    if (!cached.hit.commitment || COMMITMENTS[commitments](cached.hit)) return null;
    const reason =
      "the cached answer is a commitment (a price, a refund, a policy) and " +
      `commitments="${commitments}" does not allow speaking this match`;
    return new Verdict(this.name, reason, ["heldCommitments", "inferred"]);
  }
}

module.exports = { CommitmentRewording };
