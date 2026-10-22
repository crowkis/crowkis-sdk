"use strict";

// The CallContextTaint rule (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { setsContext } = require("../../understanding/wordRules/index.js");

const TAINTED_REASON =
  "the caller has told this call something a later answer may depend on " +
  "(a condition, an age, a plan, an instruction, a step in their own task); " +
  "a shared answer to the bare question could be wrong for them";

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

module.exports = { CallContextTaint };
