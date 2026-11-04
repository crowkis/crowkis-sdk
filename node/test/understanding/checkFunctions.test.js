"use strict";

// U1: the rewrite check and the stated-fact check are plain functions with the same answers as before.
// The same cases as python/tests/understanding/test_check_functions.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { statedFactIrrelevant } = require("../../src/understanding/factRelevance.js");
const { acceptedRewrite } = require("../../src/understanding/rewriteCheck.js");
const { TurnFrame } = require("../../src/understanding/turnFrame.js");
const { WordReading } = require("../../src/understanding/wordRuleClassifier.js");

function frame({ confidence = 0.9, changes = false, fact = "my car was hit", type = "other" } = {}) {
  return TurnFrame.fromDict({ kind: "general", subject: "none", confidence,
    fact_relevance: [{ fact, type, changes_answer: changes }] });
}

function call(stated = []) {
  return { values: {}, stated: () => stated, facts: () => [], isPersonal: () => false, isContextDependent: () => false };
}

test("a fact the model is sure of may be left out", () => {
  assert.strictEqual(statedFactIrrelevant("my car was hit", frame()), true);
});

test("unsure, changing or high-risk facts count", () => {
  assert.strictEqual(statedFactIrrelevant("my car was hit", frame({ confidence: 0.3 })), false);
  assert.strictEqual(statedFactIrrelevant("my car was hit", frame({ changes: true })), false);
  assert.strictEqual(statedFactIrrelevant("my car was hit", null), false);
  assert.strictEqual(statedFactIrrelevant("I am allergic to peanuts", frame({ fact: "I am allergic to peanuts" })), false);
});

test("each clause needs its own entry", () => {
  assert.strictEqual(statedFactIrrelevant("my car was hit and my husband has a heart condition", frame()), false);
});

test("a safe rewrite keys the turn", () => {
  const text = "how do i reset a password";
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), " How do I reset a password? ", call()), "How do I reset a password?");
});

test("unsafe rewrites keep the caller's words", () => {
  const text = "how do i reset a password";
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), "", call()), null);
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), null, call()), null);
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), "How does Priya reset a password?", call()), null);
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), "How do I reset password 4821?", call()), null);
  assert.strictEqual(acceptedRewrite(text, new WordReading(text), "How do I reset a password?", call(["I'm 70"])), null);
});
