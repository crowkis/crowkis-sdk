"use strict";

// The PersonalTemplate rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { unfinished } = require("../../understanding/wordRules/index.js");

/**
 * An answer about the caller's own records is shared only as a shape with this call's declared
 * values taken out; this rule says when it cannot be (the call was told something, the answer
 * does not answer, the turn was cut off, or no shape could be made).
 */
class PersonalTemplate {
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
    return new Verdict(this.name, "about this caller, with no declared value to make a shared answer shape from", [], OUTCOME.PRIVATE);
  }
}

module.exports = { PersonalTemplate };
