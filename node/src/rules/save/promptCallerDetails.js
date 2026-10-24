"use strict";

// The PromptCallerDetails rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { repeatsPromptDetails } = require("../../understanding/wordRules/index.js");
const { COUNTER } = require("../../runtime/stats.js");

/**
 * The model read a system prompt that names this caller, and its answer repeats that: right for
 * this caller only, never a shared answer or shape.
 */
class PromptCallerDetails {
  get name() {
    return "PromptCallerDetails";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.instructions || !repeatsPromptDetails(answer.answer, answer.text, answer.instructions, answer.call.agentKey())) {
      return null;
    }
    return new Verdict(this.name, "kept to this call: the answer repeats a detail about the caller from the system prompt",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

module.exports = { PromptCallerDetails };
