"use strict";

// v4 P1: each question, hit and save rule alone, on a fake call (fixtures/rules/<stage>/<Rule>.json),
// the same cases as python/tests/rules/test_stage_rules.py.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const hit = require("../../src/rules/hit/index.js");
const question = require("../../src/rules/question/index.js");
const save = require("../../src/rules/save/index.js");
const { CallState } = require("../../callstate.js");
const { TurnFrame } = require("../../turn.js");
const { CachedAnswer } = require("../../src/turns/cachedAnswer.js");
const { ChatAnswer } = require("../../src/turns/chatAnswer.js");
const { ChatTurn } = require("../../src/turns/chatTurn.js");
const { Hit } = require("../../src/turns/hit.js");
const { Verdict: ChatVerdict } = require("../../verify.js");
const { ModelAnswer } = require("../../src/turns/modelAnswer.js");
const { VoiceTurn } = require("../../src/turns/voiceTurn.js");
const { WordRuleClassifier } = require("../../src/understanding/wordRuleClassifier.js");
const { FakeCall } = require("./fakeCall.js");

const RULES_DIR = path.join(__dirname, "..", "..", "..", "fixtures", "rules");
const RULES = { ...question, ...hit, ...save };
const CASES = fs.readdirSync(RULES_DIR).sort().flatMap((stage) =>
  fs.readdirSync(path.join(RULES_DIR, stage)).sort().flatMap((file) => {
    const data = JSON.parse(fs.readFileSync(path.join(RULES_DIR, stage, file), "utf8"));
    return data.cases.map((c) => ({ ...c, rule: data.rule, stage: data.stage, subject: data.subject || "voice" }));
  }));

const pythonName = (name) => name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);

// The fixtures name rule settings as Python does.
const RULE_ARG_NAMES = { confidence_floor: "confidenceFloor" };
const ruleArgs = (args = {}) => Object.fromEntries(Object.entries(args).map(([name, value]) => [RULE_ARG_NAMES[name] || name, value]));

function subject(testCase, call) {
  if (testCase.subject === "chat_answer") {
    const frame = testCase.frame ? TurnFrame.fromDict(testCase.frame) : null;
    const verdict = new ChatVerdict(true, "shared", [], testCase.verdict.question, testCase.verdict.attributes);
    return new ChatAnswer(testCase.answer.split(/\s+/).filter(Boolean).join(" "), verdict, frame,
      CallState.fromDict(testCase.state), { instructions: testCase.instructions, promptKey: [null, null, "chat"] });
  }
  if (testCase.subject === "chat") {
    return new ChatTurn(TurnFrame.fromDict(testCase.frame), testCase.say, CallState.fromDict(testCase.state));
  }
  const turn = new VoiceTurn(testCase.say, call, new WordRuleClassifier().classify(testCase.say.trim()));
  if (testCase.stage === "question") return turn;
  if (testCase.stage === "hit") return new CachedAnswer(turn, Hit.fromAgent(testCase.hit), performance.now());
  return new ModelAnswer(testCase.say, testCase.answer, call.key, call, {
    private: Boolean(testCase.private), instructions: testCase.instructions || null,
    cacheable: testCase.cacheable === undefined ? true : testCase.cacheable,
  });
}

for (const testCase of CASES) {
  test(`${testCase.rule}: ${testCase.name}`, async () => {
    const call = new FakeCall(testCase.call);
    const verdict = await new RULES[testCase.rule](ruleArgs(testCase.rule_args)).check(subject(testCase, call));
    assert.strictEqual(Boolean(verdict), testCase.objects);
    if (verdict) {
      assert.strictEqual(verdict.rule, testCase.rule);
      assert.deepStrictEqual(verdict.counts.map(pythonName), testCase.counts);
      assert.strictEqual(verdict.outcome, testCase.outcome || null);
      assert.strictEqual(verdict.route, testCase.route || null);
      if (testCase.reason !== undefined) assert.strictEqual(verdict.reason, testCase.reason);
    }
  });
}

test("every rule has cases both ways", () => {
  for (const name of new Set(CASES.map((c) => c.rule))) {
    const outcomes = new Set(CASES.filter((c) => c.rule === name).map((c) => c.objects));
    assert.deepStrictEqual([...outcomes].sort(), [false, true], name);
  }
  assert.strictEqual(new Set(CASES.map((c) => c.rule)).size, 47);
});

test("the taint rule marks the call", async () => {
  const call = new FakeCall();
  const said = "I am allergic to peanuts";
  await new question.CallContextTaint().check(new VoiceTurn(said, call, new WordRuleClassifier().classify(said)));
  assert.strictEqual(call.tainted, true);
});
