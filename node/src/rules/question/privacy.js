"use strict";

// Question rules about what the caller told this call.

const { Verdict } = require("../../turns/verdict.js");
const { privateChain, setsContext } = require("../../understanding/wordRules.js");

const TAINTED_REASON =
  "the caller has told this call something a later answer may depend on " +
  "(a condition, an age, a plan, an instruction, a step in their own task); " +
  "a shared answer to the bare question could be wrong for them";
const PRIVATE_CHAIN_REASON =
  "a follow-up to a private turn of this call: its answer depends on what " +
  "this caller said, so it is never answered from a shared cache";

/**
 * Once the caller tells the call something a later answer may depend on (a condition, an age,
 * a plan, an instruction), every later turn of the call is private. The voice default until an
 * understander can tell which stated facts change an answer.
 */
class CallContextTaint {
  get name() {
    return "CallContextTaint";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.call.tainted || setsContext(turn.text))) return null;
    turn.call.markTainted();
    return new Verdict(this.name, TAINTED_REASON, ["refusedPrivate", "inferred"]);
  }
}

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

module.exports = { CallContextTaint, PrivateChain };
