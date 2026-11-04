"use strict";

// v4 P1: the understanding slots hold today's word rules and no rewrite, the same cases as
// python/tests/understanding/test_word_rule_classifier.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { NoRewrite } = require("../../src/understanding/noRewrite.js");
const { WordRuleClassifier } = require("../../src/understanding/wordRuleClassifier.js");
const { isContextDependent } = require("../../src/understanding/wordRules/followUp.js");
const { isPersonal } = require("../../src/understanding/wordRules/personal.js");

test("the reading is the word rules", () => {
  for (const text of ["my order 48213 has not arrived where is it", "and how long will that take",
    "what is your refund policy", ""]) {
    const reading = new WordRuleClassifier().classify(text);
    assert.strictEqual(reading.isPersonal, isPersonal(text), text);
    assert.strictEqual(reading.isContextDependent, isContextDependent(text), text);
  }
});

test("no rewrite keeps the caller's words as the key", () => {
  const reading = new WordRuleClassifier().classify("what is your refund policy");
  assert.strictEqual(new NoRewrite().rewrite("what is your refund policy", reading), null);
});
