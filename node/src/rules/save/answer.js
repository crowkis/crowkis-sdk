"use strict";

// Save rules: when the model's answer to a turn is not shared with later callers.
// A family of small rules, in the order an answer is checked. Each verdict says what happened
// to the answer (`outcome`) in the words record() reports.

const { Verdict } = require("../../turns/verdict.js");
const { leaks, repeatsIdentifier, repeatsPromptDetails, unfinished } = require("../../understanding/wordRules.js");

const KEPT = "kept";
const PRIVATE = "private";
const NON_ANSWER = "non_answer";
const NOT_SAVED = "not_saved";

class SaveRule {
  get floor() {
    return false;
  }
}

/** A model that said nothing has nothing to save. */
class EmptyAnswer extends SaveRule {
  get name() {
    return "EmptyAnswer";
  }

  check(answer) {
    if (typeof answer.answer === "string" && answer.answer.trim()) return null;
    return new Verdict(this.name, "the model returned an empty answer", ["emptyAnswers"], NON_ANSWER);
  }
}

/** A follow-up with no earlier turn to key it on cannot be saved. */
class NoKey extends SaveRule {
  get name() {
    return "NoKey";
  }

  check(answer) {
    if (answer.key !== null) return null;
    return new Verdict(this.name, "a follow-up with no earlier turn to key it on", [], NOT_SAVED);
  }
}

/** An answer built from a tool's result stays in the call. */
class ToolResult extends SaveRule {
  get name() {
    return "ToolResult";
  }

  check(answer) {
    if (!answer.private) return null;
    return new Verdict(this.name, "kept to this call: the answer was built from a tool's result", ["notShareable"], KEPT);
  }
}

/**
 * The model read a system prompt that names this caller, and its answer repeats that: right for
 * this caller only, never a shared answer or shape.
 */
class PromptCallerDetails extends SaveRule {
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
      ["notShareable"], PRIVATE);
  }
}

/**
 * An answer about the caller's own records is shared only as a shape with this call's declared
 * values taken out; this rule says when it cannot be (the call was told something, the answer
 * does not answer, the turn was cut off, or no shape could be made).
 */
class PersonalTemplate extends SaveRule {
  get name() {
    return "PersonalTemplate";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.isPersonal) return null;
    if (answer.call.tainted || answer.isNonAnswer || unfinished(answer.text)) return this.refusal();
    return null;
  }

  /** The verdict when no shared shape is made from a personal answer. */
  refusal() {
    return new Verdict(this.name, "about this caller, with no declared value to make a shared answer shape from", [], PRIVATE);
  }
}

/** Once the caller told the call something an answer may depend on, nothing more is shared. */
class TaintedCall extends SaveRule {
  get name() {
    return "TaintedCall";
  }

  check(answer) {
    if (!answer.call.tainted) return null;
    return new Verdict(this.name, "kept to this call: the caller told it something the answer may depend on",
      ["notShareable"], KEPT);
  }
}

/** An answer decide() did not let be shared (the model read more than the question) stays in the call. */
class NotShareable extends SaveRule {
  get name() {
    return "NotShareable";
  }

  check(answer) {
    if (answer.cacheable) return null;
    return new Verdict(this.name, "kept to this call: the answer depends on what this caller said", ["notShareable"], KEPT);
  }
}

/** An answer holding a value declared for this call is never shared. */
class DeclaredValue extends SaveRule {
  get name() {
    return "DeclaredValue";
  }

  check(answer) {
    if (!leaks(answer.answer, answer.call.values)) return null;
    return new Verdict(this.name, "kept to this call: the answer contains a value declared for this call",
      ["notShareable"], PRIVATE);
  }
}

/**
 * An answer repeating a number or ID this caller said is never shared. Its model read only the
 * question, so this can only come from an app that sent it the whole call.
 */
class CallerIdentifier extends SaveRule {
  get name() {
    return "CallerIdentifier";
  }

  check(answer) {
    if (!repeatsIdentifier(answer.answer, answer.call.saidIdentifiers())) return null;
    return new Verdict(this.name, "kept to this call: the answer repeats a number or ID this caller said",
      ["notShareable"], PRIVATE);
  }
}

/** An answer that asks back or does not answer is not saved. */
class NonAnswer extends SaveRule {
  get name() {
    return "NonAnswer";
  }

  check(answer) {
    if (!answer.isNonAnswer) return null;
    return new Verdict(this.name, "not saved: the answer asks back or does not answer", ["notShareable"], NON_ANSWER);
  }
}

module.exports = {
  CallerIdentifier,
  DeclaredValue,
  EmptyAnswer,
  NoKey,
  NonAnswer,
  NotShareable,
  PersonalTemplate,
  PromptCallerDetails,
  TaintedCall,
  ToolResult,
};
