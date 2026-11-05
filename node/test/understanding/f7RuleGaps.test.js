"use strict";

// F7: the three rule gaps the F6 stress run found; the same cases as python/tests/test_f7_rule_gaps.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { RuleSet } = require("../../src/rules/ruleSet.js");
const { ACTION_CLAIM } = require("../../src/understanding/wordRules/chat.js");
const { isContextDependent } = require("../../src/understanding/wordRules/followUp.js");

const FOLLOW_UPS = [
  "Do I need an ID proof for that?", "How many times do you try again after that?",
  "Compare it with the MacBook Air", "Done, what next?", "Yes, who is this?", "No, what is this about?",
];
const STANDALONE = [
  "What are your opening hours?", "Is it refundable if I cancel within a week?",
  "What does it cost to send a parcel?", "What is the refund policy for this product?",
  "How do I return it?", "Do you ship to this country?", "What happens after that date passes?",
  "No refund policy applies to sale items?", "Yes, what are your opening hours?", "Yes, do you deliver on Sundays?",
];

test("follow-ups are context dependent", () => {
  for (const text of FOLLOW_UPS) assert.ok(isContextDependent(text), text);
});

test("general questions stay shareable", () => {
  for (const text of STANDALONE) assert.ok(!isContextDependent(text), text);
});

test("an action promise is not shared on voice", () => {
  assert.ok(RuleSet.voice().sharing.names.includes("VoiceActionClaim"));
  assert.ok(ACTION_CLAIM.test("I will add milk and eggs to your shopping list."));
  assert.ok(ACTION_CLAIM.test("Sure, I'll book that for you."));
  assert.ok(ACTION_CLAIM.test("Sure, I’ll book that."));
  assert.ok(ACTION_CLAIM.test("Milk and eggs have been added to your list."));
  assert.ok(!ACTION_CLAIM.test("You can add items to a list in the app."));
  assert.ok(!ACTION_CLAIM.test("We will be open until nine."));
});
