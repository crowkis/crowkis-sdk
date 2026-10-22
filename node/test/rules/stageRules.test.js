"use strict";

// v4 P1: each question, hit and save rule alone, on a fake call (fixtures/rules/<stage>/<Rule>.json),
// the same cases as python/tests/rules/test_stage_rules.py.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const guards = require("../../src/rules/hit/guards.js");
const floor = require("../../src/rules/question/floor.js");
const followUp = require("../../src/rules/question/followUp.js");
const operational = require("../../src/rules/question/operational.js");
const policy = require("../../src/rules/question/policy.js");
const privacy = require("../../src/rules/question/privacy.js");
const save = require("../../src/rules/save/answer.js");
const { CachedAnswer } = require("../../src/turns/cachedAnswer.js");
const { ModelAnswer } = require("../../src/turns/modelAnswer.js");
const { VoiceTurn } = require("../../src/turns/voiceTurn.js");
const { FakeCall } = require("./fakeCall.js");

const RULES_DIR = path.join(__dirname, "..", "..", "..", "fixtures", "rules");
const RULES = { ...guards, ...floor, ...followUp, ...operational, ...policy, ...privacy, ...save };
const CASES = fs.readdirSync(RULES_DIR).sort().flatMap((stage) =>
  fs.readdirSync(path.join(RULES_DIR, stage)).sort().flatMap((file) => {
    const data = JSON.parse(fs.readFileSync(path.join(RULES_DIR, stage, file), "utf8"));
    return data.cases.map((c) => ({ ...c, rule: data.rule, stage: data.stage }));
  }));

const pythonName = (name) => name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);

function subject(testCase, call) {
  const turn = new VoiceTurn(testCase.say, call);
  if (testCase.stage === "question") return turn;
  if (testCase.stage === "hit") return new CachedAnswer(turn, testCase.hit, performance.now());
  return new ModelAnswer(testCase.say, testCase.answer, call.key, call, {
    private: Boolean(testCase.private), instructions: testCase.instructions || null,
    cacheable: testCase.cacheable === undefined ? true : testCase.cacheable,
  });
}

for (const testCase of CASES) {
  test(`${testCase.rule}: ${testCase.name}`, async () => {
    const call = new FakeCall(testCase.call);
    const verdict = await new RULES[testCase.rule]().check(subject(testCase, call));
    assert.strictEqual(Boolean(verdict), testCase.objects);
    if (verdict) {
      assert.strictEqual(verdict.rule, testCase.rule);
      assert.deepStrictEqual(verdict.counts.map(pythonName), testCase.counts);
      assert.strictEqual(verdict.outcome, testCase.outcome || null);
    }
  });
}

test("every rule has cases both ways", () => {
  for (const name of new Set(CASES.map((c) => c.rule))) {
    const outcomes = new Set(CASES.filter((c) => c.rule === name).map((c) => c.objects));
    assert.deepStrictEqual([...outcomes].sort(), [false, true], name);
  }
  assert.strictEqual(new Set(CASES.map((c) => c.rule)).size, 24);
});

test("the taint rule marks the call", async () => {
  const call = new FakeCall();
  await new privacy.CallContextTaint().check(new VoiceTurn("I am allergic to peanuts", call));
  assert.strictEqual(call.tainted, true);
});
