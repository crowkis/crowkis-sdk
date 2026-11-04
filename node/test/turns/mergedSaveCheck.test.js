"use strict";

// v4 P5 item 3: the merged save check. Voice with an understander gains PrivateWord and ActionClaim; Chat
// gains ToolResult, CallerIdentifier and the bounded write. The same cases as
// python/tests/test_merged_save_check.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../src/client/agent.js");
const { CallSession } = require("../../src/channels/callSession.js");
const { CallState } = require("../../src/state/callState.js");
const { TurnFrame } = require("../../src/understanding/model/frame.js");
const { WordRuleClassifier } = require("../../src/understanding/slots.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

const QUESTION = "What is your refund policy?";

class Store {
  constructor() {
    this.shared = new Map();
  }

  async cgetHit() {
    return null;
  }

  async cset(query, response) {
    this.shared.set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

function voiceOn(store, options = {}) {
  return new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });
}

test("voice: a word from a private turn is never shared", async () => {
  const store = new Store();
  const session = voiceOn(store, { classifier: new WordRuleClassifier() });
  await session.record(await session.decide("my order 48213 for Sarah Khan has not arrived"), "I will check order 48213.");
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, "Sarah, refunds take five business days.");
  assert.strictEqual(decision.saveRule, "VoicePrivateWord");
  assert.strictEqual(store.shared.size, 0);
});

test("voice: an answer saying it was done is never shared", async () => {
  const store = new Store();
  const session = voiceOn(store, { classifier: new WordRuleClassifier() });
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, "I have cancelled your order and refunded you.");
  assert.strictEqual(decision.saveRule, "VoiceActionClaim");
  assert.strictEqual(store.shared.size, 0);
});

test("voice, must still work: without an understander nothing changes", async () => {
  const store = new Store();
  const session = voiceOn(store);
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, "I have cancelled your order and refunded you.");
  assert.strictEqual(store.shared.has("what is your refund policy"), true);
});

class ChatAgent {
  constructor({ slowMs = 0 } = {}) {
    this.slowMs = slowMs;
    this.saved = [];
  }

  async ask() {
    return { route: "expensive", answer: null, confidence: 0 };
  }

  async learn(key, answer) {
    if (this.slowMs) await new Promise((resolve) => { this.timer = setTimeout(resolve, this.slowMs); });
    this.saved.push([key, answer]);
  }
}

const scripted = { understand: () => TurnFrame.fromDict({
  kind: "general", subject: "none", confidence: 0.9, question: QUESTION, question_type: "policy",
}) };

test("chat: an answer built from a tool is never shared", async () => {
  const agent = new ChatAgent();
  const session = new CallSession(agent, scripted);
  const result = await session.handle("what is your refund policy");
  assert.strictEqual(await session.recordAnswer(result, "Your refund of 499 was sent.", { private: true }), "refused:tool_result");
  assert.deepStrictEqual(agent.saved, []);
});

test("chat: an answer repeating an ID the user said is never shared", async () => {
  const session = new CallSession(new ChatAgent(), scripted);
  await session.handle("my order is ORD55821");
  const result = await session.handle("what is your refund policy");
  // PrivateWord refuses this first today (an ID turn is never shared); the identifiers are kept apart.
  assert.strictEqual(session.saveCheck("Refunds for ORD55821 take five days.", result.verdict), "private_word");
  session.state.privateWords = [];
  assert.strictEqual(await session.recordAnswer(result, "Refunds for ORD55821 take five days."), "refused:caller_identifier");
});

test("chat: a slow server costs the chat one write, not a stall", async (t) => {
  t.mock.method(console, "warn", () => {});
  const agent = new ChatAgent({ slowMs: 2000 });
  t.after(() => clearTimeout(agent.timer));
  const session = new CallSession(agent, scripted, { latencyBudgetMs: 50 });
  const result = await session.handle("what is your refund policy");
  const started = performance.now();
  assert.strictEqual(await session.recordAnswer(result, "Refunds take five days."), "slow_write");
  assert.ok(performance.now() - started < 1000);
  assert.strictEqual(session.stats().slow_writes, 1);
});

test("chat: a refused write is an outcome, not an error", async () => {
  // v4 P5.5: the write's error boundary is the writer's; with and without a latency budget.
  for (const latencyBudgetMs of [null, 50]) {
    const agent = new ChatAgent();
    agent.learn = async () => { throw new Error("tenant limit"); };
    const session = new CallSession(agent, scripted, { latencyBudgetMs });
    const result = await session.handle("what is your refund policy");
    assert.strictEqual(await session.recordAnswer(result, "Refunds take five days."), "refused:write_failed");
    assert.strictEqual(session.counts.save_refused, 1);
  }
});

test("chat, must still work: a plain answer is saved", async () => {
  const agent = new ChatAgent();
  const session = new CallSession(agent, scripted);
  const result = await session.handle("what is your refund policy");
  assert.strictEqual(await session.recordAnswer(result, "Refunds take five days."), "saved");
  assert.deepStrictEqual(agent.saved.map(([, answer]) => answer), ["Refunds take five days."]);
});

test("chat: the user's identifiers are exported hashed", async () => {
  // Chat restores its state from the app's store each turn, so a later turn's check needs them (M2).
  // Hashed like the private words beside them: the raw value is never in the export.
  const session = new CallSession(new ChatAgent(), scripted);
  await session.handle("my order is ORD55821");
  const exported = session.export().state;
  assert.ok(session.state.identifiers.length > 0);
  assert.deepStrictEqual(exported.identifiers, session.state.identifiers);
  assert.ok(!JSON.stringify(exported).toLowerCase().includes("55821"));
  assert.deepStrictEqual(CallState.fromDict(exported).identifiers, session.state.identifiers);
});
