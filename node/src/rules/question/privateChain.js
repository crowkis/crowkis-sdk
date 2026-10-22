"use strict";

// The PrivateChain rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { privateChain } = require("../../understanding/wordRules.js");

const PRIVATE_CHAIN_REASON =
  "a follow-up to a private turn of this call: its answer depends on what " +
  "this caller said, so it is never answered from a shared cache";

/**
 * A follow-up to a private turn of the call, or any turn after an urgent one, is private: its
 * answer depends on what this caller said.
 */
class PrivateChain {
  get name() {
    return "PrivateChain";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const followsPrivate = turn.isContextDependent && privateChain(turn.call.chain() || [], turn.call.minWords);
    if (!(followsPrivate || turn.call.afterUrgent(turn.text))) return null;
    return new Verdict(this.name, PRIVATE_CHAIN_REASON, ["refusedPrivate", "inferred"]);
  }
}

module.exports = { PrivateChain };
