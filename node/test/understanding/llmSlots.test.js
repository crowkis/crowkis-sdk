"use strict";

// v4 P4 step 4: the model-backed slots (LLMClassifier, LLMRewriter, ReplayRewriter) and a rewritten
// turn's answer saved under the question it was looked up with. The same cases as
// python/tests/understanding/test_llm_slots.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { LLMClassifier, LLMRewriter, LLMUnderstander, ReplayRewriter } = require("../../index.js");
const { TurnFrame } = require("../../src/understanding/turnFrame.js");
const { FrameReading } = require("../../src/understanding/frameReading.js");
const { WordRuleClassifier } = require("../../src/understanding/wordRuleClassifier.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

const GENERAL = { kind: "general", subject: "none", confidence: 0.95, question: "What is the refund policy?" };

class Store {
  constructor() {
    this.shared = new Map();
  }

  async cgetHit(query) {
    const found = this.shared.get(query);
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
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

// A stand-in for the app's LLM: answers every turn with `frame` and remembers what it was sent.
class Model {
  constructor({ frame = GENERAL, raw = null } = {}) {
    this.frame = frame;
    this.raw = raw;
    this.sent = [];
    this.complete = async (messages) => {
      this.sent.push(messages);
      return this.raw !== null ? this.raw : JSON.stringify(this.frame);
    };
  }
}

function slots(model) {
  const understander = new LLMUnderstander(model.complete);
  return { classifier: new LLMClassifier(understander), rewriter: new LLMRewriter(understander) };
}

function sessionOn(store, options = {}) {
  return new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });
}

function reading(frame = {}) {
  return new FrameReading(TurnFrame.fromDict({ ...GENERAL, ...frame }));
}

test("a confident general turn may be shared under its question", () => {
  assert.strictEqual(reading().isPersonal, false);
  assert.strictEqual(reading().question, "What is the refund policy?");
});

test("anything else reads as personal and is not rewritten", () => {
  for (const frame of [{ kind: "personal" }, { kind: "live" }, { kind: "action" }, { kind: "sensitive" },
    { abstain: true }, { urgent: true }, { subject: "self" }, { confidence: 0.3 },
    { entities: [{ text: "48213", type: "id_number", identifying: true }] }]) {
    assert.strictEqual(reading(frame).isPersonal, true, JSON.stringify(frame));
    assert.strictEqual(reading(frame).question, null, JSON.stringify(frame));
  }
});

test("a follow-up depends on the call", () => {
  assert.strictEqual(reading({ uses_state: true }).isContextDependent, true);
  assert.strictEqual(reading({ kind: "dialogue" }).isContextDependent, true);
  assert.strictEqual(reading().isContextDependent, false);
});

test("a rewritten answer is saved under the question and found by another wording", async () => {
  const store = new Store();
  const first = sessionOn(store, slots(new Model()));
  const decision = await first.decide("can you tell me about your refund policy");
  await first.record(decision, "Refunds take five business days.");
  assert.strictEqual(store.shared.get("What is the refund policy?"), "Refunds take five business days.");
  const served = await sessionOn(store, slots(new Model())).decide("how do refunds work at your store");
  assert.strictEqual(served.action, "serve");
});

test("the model is asked once per turn", async () => {
  const model = new Model();
  await sessionOn(new Store(), slots(model)).decide("whats ur refund policy pls");
  assert.strictEqual(model.sent.length, 1);
});

test("the model sees the turn alone", async () => {
  const model = new Model();
  const session = sessionOn(new Store(), slots(model));
  await session.record(await session.decide("my name is Priya Sharma and I live in Pune"), "Hello Priya.");
  await session.decide("whats ur refund policy pls");
  assert.strictEqual(JSON.stringify(model.sent[model.sent.length - 1]).includes("Priya"), false);
});

test("output that is not a frame keeps the turn private", async () => {
  const store = new Store();
  const session = sessionOn(store, slots(new Model({ raw: "sorry, I cannot help" })));
  const decision = await session.decide("whats ur refund policy pls");
  assert.strictEqual(decision.cacheable, false);
  await session.record(decision, "Refunds take five business days.");
  assert.strictEqual(store.shared.size, 0);
});

test("the word rules still apply when the model says general", async () => {
  const store = new Store();
  const session = sessionOn(store, slots(new Model()));
  const decision = await session.decide("my order 48213 has not arrived where is it");
  assert.strictEqual(decision.rule, "OwnRecords");
  await session.record(decision, "Order 48213 ships tomorrow.");
  assert.strictEqual(store.shared.size, 0);
});

test("ReplayRewriter: an exact repeat is keyed on the verified question", () => {
  const rewriter = new ReplayRewriter({ "What is the refund policy?": "policy" });
  const words = new WordRuleClassifier().classify("what is the refund policy");
  assert.strictEqual(rewriter.rewrite("what is the refund policy", words), "What is the refund policy?");
});

test("ReplayRewriter: another wording keeps the caller's words", () => {
  const rewriter = new ReplayRewriter({ "What is the refund policy?": "policy" });
  const words = new WordRuleClassifier().classify("how do refunds work");
  assert.strictEqual(rewriter.rewrite("how do refunds work", words), null);
});

test("ReplayRewriter: a turn read as personal is never rewritten", () => {
  const rewriter = new ReplayRewriter({ "What is the refund policy?": "policy" });
  assert.strictEqual(rewriter.rewrite("what is the refund policy", reading({ kind: "personal" })), null);
});

test("ReplayRewriter: it remembers a verified question", () => {
  const rewriter = new ReplayRewriter();
  rewriter.remember("refunds?", "What is the refund policy?");
  const words = new WordRuleClassifier().classify("Refunds?");
  assert.strictEqual(rewriter.rewrite("Refunds?", words), "What is the refund policy?");
});

// F4b: the model marked a product or a topic as identifying ("UPI", "iPhone 16") and set uses_state
// when a stand-alone question only named a topic of the call, so general questions stayed private.
test("the prompt says a product or topic is never identifying", () => {
  const { INSTRUCTIONS } = require("../../src/understanding/understanders.js");
  assert.ok(INSTRUCTIONS.includes("a plan or a condition is never identifying"));
});

test("the prompt says naming a topic of the call is not using its state", () => {
  const { INSTRUCTIONS } = require("../../src/understanding/understanders.js");
  assert.ok(INSTRUCTIONS.includes("uses_state is false for a stand-alone question that only names a topic"));
});
