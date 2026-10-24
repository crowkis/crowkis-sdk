"use strict";

// The CallerIdentifier rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { repeatsIdentifier } = require("../../understanding/wordRules/index.js");
const { COUNTER } = require("../../runtime/stats.js");

/**
 * An answer repeating a number or ID this caller said is never shared. Its model read only the
 * question, so this can only come from an app that sent it the whole call.
 */
class CallerIdentifier {
  get name() {
    return "CallerIdentifier";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!repeatsIdentifier(answer.answer, answer.call.saidIdentifiers())) return null;
    return new Verdict(this.name, "kept to this call: the answer repeats a number or ID this caller said",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

module.exports = { CallerIdentifier };
