"use strict";

// Stage 3 rules (save): nothing to share (empty or non-answers, tool results, no key, a tainted call).

const { OUTCOME } = require("../../turns/values.js");
const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { isNonAnswer } = require("../../understanding/wordRules/index.js");

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

// The ChatEmptyAnswer rule (stage 3, save; Chat, "empty").
/** An empty answer has nothing to save. */
class ChatEmptyAnswer {
  get name() {
    return "ChatEmptyAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.text) return null;
    return new Verdict(this.name, "empty");
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

// The ChatNonAnswer rule (stage 3, save; Chat, "non_answer").
/** An answer that asks back or does not answer is not saved. */
class ChatNonAnswer {
  get name() {
    return "ChatNonAnswer";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!isNonAnswer(answer.text)) return null;
    return new Verdict(this.name, "non_answer");
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

// The ChatToolResult rule (stage 3, save; Chat).
/**
 * Voice's ToolResult on Chat (v4): an answer the app built from a tool's result
 * (recordAnswer(..., { private: true })) stays in the chat.
 */
class ChatToolResult {
  get name() {
    return "ChatToolResult";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!answer.private) return null;
    return new Verdict(this.name, "tool_result");
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

module.exports = { EmptyAnswer, ChatEmptyAnswer, NonAnswer, ChatNonAnswer, ToolResult, ChatToolResult, NoKey, NotShareable, TaintedCall };
