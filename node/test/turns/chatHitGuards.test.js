"use strict";

// v4 P5 item 2: Chat runs the hit guards every channel runs (DifferentQuestion, CommitmentRewording on
// exact questions only, PiiPlaceholder) and keeps the question each shared answer was saved for. The
// same cases as python/tests/test_chat_hit_guards.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { CallSession } = require("../../src/channels/callSession.js");
const { ChatRuleSet } = require("../../src/rules/chatRuleSet.js");
const { TurnFrame } = require("../../src/understanding/turnFrame.js");
const { SHARED } = require("../../src/rules/ruleChecker.js");
const { questionKey } = require("../../src/runtime/questionRecords.js");
const { _waitForWrites: waitForWrites } = require("../../src/channels/voiceSession.js");

const QUESTION = "What are your opening hours on Sunday?";

// The key-value side the question records use.
class Server {
  constructor() {
    this.tenant = "voice";
    this.values = new Map();
  }

  async get(key) {
    return this.values.get(key) ?? null;
  }

  async set(key, value) {
    this.values.set(key, value);
  }
}

// A cache that returns `hit` for every question (null: a miss).
class Agent {
  constructor(hit = null) {
    this.hit = hit;
    this.client = new Server();
    this.saved = [];
  }

  async ask() {
    if (!this.hit) return { route: "expensive", answer: null, confidence: 0 };
    return { route: "cache", confidence: 0.99, ...this.hit };
  }

  async learn(key, answer) {
    this.saved.push([key, answer]);
  }
}

const scripted = { understand: () => TurnFrame.fromDict({
  kind: "general", subject: "none", confidence: 0.9, question: QUESTION, question_type: "policy",
}) };

async function ask(agent) {
  const session = new CallSession(agent, scripted);
  return { session, result: await session.handle("what are your opening hours on sunday") };
}

test("a commitment is served only for the exact question", async () => {
  const { session, result } = await ask(new Agent({ answer: "Refunds take 5 days.", commitment: true, exact: false }));
  assert.strictEqual(result.needsModel, true);
  assert.strictEqual(session.stats().CommitmentRewording, 1);
  const exact = await ask(new Agent({ answer: "Refunds take 5 days.", commitment: true, exact: true }));
  assert.strictEqual(exact.result.text, "Refunds take 5 days.");
});

test("an answer saved for a different question is not served", async () => {
  const agent = new Agent({ answer: "We open at 10 on Saturdays." });
  agent.client.values.set(questionKey("voice", "We open at 10 on Saturdays."), JSON.stringify(["What are your opening hours on Saturday?"]));
  const { session, result } = await ask(agent);
  assert.strictEqual(result.needsModel, true);
  assert.strictEqual(session.stats().DifferentQuestion, 1);
});

test("must still work: a placeholder is never served", async () => {
  const { result } = await ask(new Agent({ answer: "Your order pii_card_ab12cd ships today." }));
  assert.strictEqual(result.needsModel, true);
});

test("must still work: a plain hit is served", async () => {
  const { result } = await ask(new Agent({ answer: "We open at 10 on Sundays." }));
  assert.deepStrictEqual([result.route, result.text], [SHARED, "We open at 10 on Sundays."]);
});

test("a saved answer keeps its question", async () => {
  const agent = new Agent();
  const { session, result } = await ask(agent);
  assert.strictEqual(await session.recordAnswer(result, "We open at 10 on Sundays."), "saved");
  await waitForWrites();
  assert.deepStrictEqual(JSON.parse(agent.client.values.get(questionKey("voice", "We open at 10 on Sundays."))), [QUESTION]);
});

test("the hit chain holds no rule that needs more than a chat hit has", () => {
  // ConfidenceBar and ScreenOnlyAnswer read call.serveAbove / call.channel, which ChatHitCall lacks.
  const { names } = ChatRuleSet.hitChain();
  assert.ok(!names.includes("ConfidenceBar"));
  assert.ok(!names.includes("ScreenOnlyAnswer"));
});
