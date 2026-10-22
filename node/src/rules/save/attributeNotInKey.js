"use strict";

// The AttributeNotInKey rule (stage 3, save; Chat, "attribute_not_in_key").

const { Verdict } = require("../../turns/verdict.js");
const { escapeRegExp } = require("../../understanding/wordRules/index.js");

/**
 * An answer that names one of this chat's attributes (a region, a tier) which did not enter the key
 * would reach users it does not fit. A value the question itself says ("the capital of France") is
 * part of what was asked.
 */
class AttributeNotInKey {
  get name() {
    return "AttributeNotInKey";
  }

  get floor() {
    return false;
  }

  check(answer) {
    const verdict = answer.verdict;
    for (const [name, attr] of Object.entries(answer.state.attributes)) {
      const pattern = attr.value ? new RegExp(`\\b${escapeRegExp(attr.value)}\\b`, "i") : null;
      if (!(name in verdict.attributes) && pattern && pattern.test(answer.text) && !pattern.test(verdict.question || "")) {
        return new Verdict(this.name, "attribute_not_in_key");
      }
    }
    return null;
  }
}

module.exports = { AttributeNotInKey };
