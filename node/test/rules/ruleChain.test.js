"use strict";

// v4 P1: RuleChain and RuleSet (first objection wins, the floor lock, the voice defaults), the
// same cases as python/tests/rules/test_rule_chain.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { CrowkisError } = require("../../index.js");
const { FloorRuleLocked, RuleChain, UnknownRule } = require("../../src/rules/chain.js");
const { RuleSet } = require("../../src/rules/ruleSet.js");
const { Verdict } = require("../../src/turns/values.js");

class Objects {
  constructor(name, objects, floor = false) {
    Object.assign(this, { name, objects, floor, seen: 0 });
  }

  check() {
    this.seen += 1;
    return this.objects ? new Verdict(this.name, `${this.name} objects`) : null;
  }
}

test("the first objection wins and later rules do not run", async () => {
  const later = new Objects("Later", true);
  const chain = new RuleChain([new Objects("Quiet", false), new Objects("First", true), later]);
  assert.strictEqual((await chain.firstObjection("turn")).rule, "First");
  assert.strictEqual(later.seen, 0);
});

test("no objection lets the subject through", async () => {
  assert.strictEqual(await new RuleChain([new Objects("Quiet", false)]).firstObjection("turn"), null);
  assert.strictEqual(await new RuleChain([]).firstObjection("turn"), null);
});

test("a policy rule can be turned off", async () => {
  const chain = new RuleChain([new Objects("Policy", true), new Objects("Other", false)]).without(["Policy"]);
  assert.deepStrictEqual(chain.names, ["Other"]);
  assert.strictEqual(await chain.firstObjection("turn"), null);
});

test("a floor rule stays on without the unsafe flag", () => {
  const chain = new RuleChain([new Objects("Floor", true, true)]);
  assert.throws(() => chain.without(["Floor"]), (error) => error instanceof FloorRuleLocked && error instanceof CrowkisError);
  assert.deepStrictEqual(chain.without(["Floor"], { unsafe: true }).names, []);
});

test("a group holding a floor rule is locked too", () => {
  const chain = new RuleChain([new RuleChain([new Objects("Floor", true, true)], { name: "Group" })]);
  assert.throws(() => chain.without(["Group"]), FloorRuleLocked);
  assert.deepStrictEqual(chain.without(["Group"], { unsafe: true }).names, []);
});

test("collecting every objection refuses a rule that answers with a promise", () => {
  const later = { name: "Later", floor: false, check: async () => null };
  assert.throws(() => new RuleChain([later]).allObjections("turn"), TypeError);
});

test("the voice defaults are today's rules in today's order", () => {
  const rules = RuleSet.voice();
  assert.deepStrictEqual(rules.beforeFiller.names, ["EmptyTurn"]);
  assert.deepStrictEqual(rules.question.names, ["CallContextTaint", "TooShort", "CutOff", "OwnRecords",
    "FollowUpWithoutContext", "PrivateChain"]);
  assert.deepStrictEqual(rules.hit.names, ["ConfidenceBar", "TemplateSlotMissing", "PiiPlaceholder", "DifferentQuestion",
    "ShortTurnUnvouched", "CommitmentRewording", "ScreenOnlyAnswer"]);
  assert.deepStrictEqual(rules.answerGiven.names, ["EmptyAnswer"]);
  assert.deepStrictEqual(rules.beforeSharing.names, ["NoKey", "ToolResult", "PromptCallerDetails"]);
  assert.strictEqual(rules.personal.name, "PersonalTemplate");
  assert.deepStrictEqual(rules.sharing.names, ["TaintedCall", "NotShareable", "DeclaredValue", "CallerIdentifier",
    "VoiceActionClaim", "NonAnswer"]);
});

test("rule names are a list, never one string", () => {
  assert.throws(() => new RuleChain([new Objects("PrivateChain", true)]).without("PrivateChainX"), TypeError);
  assert.throws(() => RuleSet.voice().without("PrivateChainX"), TypeError);
});

test("an unknown rule name is refused", () => {
  assert.throws(() => RuleSet.voice().without(["PrivateChainX"]), UnknownRule);
});

test("the personal answer rule cannot be turned off", () => {
  for (const unsafe of [false, true]) {
    assert.throws(() => RuleSet.voice().without(["PersonalTemplate"], { unsafe }), FloorRuleLocked);
  }
});

test("the floor rules of the voice defaults are locked", () => {
  const rules = RuleSet.voice();
  for (const floorRule of ["OwnRecords", "PromptCallerDetails"]) {
    assert.throws(() => rules.without([floorRule]), FloorRuleLocked, floorRule);
  }
  assert.ok(!rules.without(["CutOff"]).question.names.includes("CutOff"));
});
