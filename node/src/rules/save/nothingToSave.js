"use strict";

// Stage 3 rules (save): nothing to share (empty or non-answers, tool results, no key, a tainted call).

const { OUTCOME } = require("../../turns/values.js");
const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { isNonAnswer } = require("../../understanding/wordRules/answers.js");

/** A model that said nothing has nothing to save. */
class EmptyAnswer {
  get name() {
    return "EmptyAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (typeof answer.answer === "string" && answer.answer.trim()) return null;
    return new Verdict(this.name, "the model returned an empty answer", [COUNTER.EMPTY_ANSWERS], OUTCOME.NON_ANSWER);
  }
}

/** An answer that asks back or does not answer is not saved. */
class NonAnswer {
  get name() {
    return "NonAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.isNonAnswer) return null;
    return new Verdict(this.name, "not saved: the answer asks back or does not answer", [COUNTER.NOT_SHAREABLE], OUTCOME.NON_ANSWER);
  }
}

/** An answer built from a tool's result stays in the call. */
class ToolResult {
  get name() {
    return "ToolResult";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.private) return null;
    return new Verdict(this.name, "kept to this call: the answer was built from a tool's result", [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

/** A follow-up with no earlier turn to key it on cannot be saved. */
class NoKey {
  get name() {
    return "NoKey";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.key !== null) return null;
    return new Verdict(this.name, "a follow-up with no earlier turn to key it on", [], OUTCOME.NOT_SAVED);
  }
}

/** An answer decide() did not let be shared (the model read more than the question) stays in the call. */
class NotShareable {
  get name() {
    return "NotShareable";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.cacheable) return null;
    return new Verdict(this.name, "kept to this call: the answer depends on what this caller said", [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

/** Once the caller told the call something an answer may depend on, nothing more is shared. */
class TaintedCall {
  get name() {
    return "TaintedCall";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.call.tainted) return null;
    return new Verdict(this.name, "kept to this call: the caller told it something the answer may depend on",
      [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

module.exports = { EmptyAnswer, NonAnswer, ToolResult, NoKey, NotShareable, TaintedCall };
