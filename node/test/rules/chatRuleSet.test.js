"use strict";

// v4 P3: Chat's V1-V10 as a rule set, the same cases as python/tests/rules/test_chat_rule_set.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { CallState } = require("../../callstate.js");
const { TurnFrame } = require("../../turn.js");
const { RuleChecker } = require("../../verify.js");
const { FloorRuleLocked } = require("../../src/rules/chain.js");
const { ChatRuleSet } = require("../../src/rules/chatRuleSet.js");

const QUESTION = { kind: "general", subject: "none", confidence: 0.5, question: "What is your refund policy?" };

test("chat's rules are today's in today's order", () => {
  const rules = ChatRuleSet.chat(0.6);
  assert.deepStrictEqual(rules.decisive.names, ["UrgentTurn", "TaskStep"]);
  assert.deepStrictEqual(rules.frame.names, ["UncertainFrame", "NotGeneral", "AboutSomeone", "NoQuestion"]);
  assert.deepStrictEqual(rules.question.allNames, ["IdentifyingDetails", "Ungrounded", "UnresolvedReference",
    "V7_LostOrDropped", "LostDetail", "StatedFacts"]);
});

test("a rule inside the V7 group can be turned off", () => {
  const rules = ChatRuleSet.chat(0.6).without(["StatedFacts"]);
  assert.ok(!rules.question.allNames.includes("StatedFacts"));
  assert.ok(rules.question.allNames.includes("LostDetail"));
});

test("chat's floor rules are locked", () => {
  for (const floorRule of ["UrgentTurn", "AboutSomeone", "IdentifyingDetails"]) {
    assert.throws(() => ChatRuleSet.chat(0.6).without([floorRule]), FloorRuleLocked, floorRule);
  }
});

test("must still work: a confidence floor changed later is read", () => {
  const checker = new RuleChecker();
  const frame = TurnFrame.fromDict(QUESTION);
  assert.deepStrictEqual(checker.check(frame, "what is your refund policy", new CallState()).reasons, ["V2_uncertain"]);
  checker.confidenceFloor = 0.4;
  assert.strictEqual(checker.check(frame, "what is your refund policy", new CallState()).shared, true);
});
