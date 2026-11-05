"use strict";

// v4 P5 item 5: with an understander, voice answers live in kb=<version>;channel=<name>, so switching
// understanders or knowledge is a deliberate new version. Without one, nothing is sent (as before). The
// same cases as python/tests/understanding/test_knowledge_segment.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../src/client/agent.js");
const { KnowledgeSegment } = require("../../src/keys/knowledgeSegment.js");
const { RuleChecker } = require("../../src/rules/ruleChecker.js");
const { REALTIME, VOICE } = require("../../src/turns/values.js");
const { WordRuleClassifier } = require("../../src/understanding/slots.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

// A cache whose answers live per segment; it records what each call sent.
class SegmentedStore {
  constructor() {
    this.answers = new Map();
    this.sent = [];
  }

  async cgetHit(query, options = {}) {
    this.sent.push(`get ${options.segment ?? null}`);
    const found = this.answers.get(`${options.segment ?? null}|${query}`);
    if (found === undefined) return null;
    return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }

  async cset(query, response, options = {}) {
    this.sent.push(`set ${options.segment ?? null}`);
    this.answers.set(`${options.segment ?? null}|${query}`, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const sessionOn = (store, options = {}) => new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });

async function save(store, options = {}) {
  const session = sessionOn(store, options);
  await session.record(await session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.");
}

test("every lookup and save carries the version with an understander", async () => {
  const store = new SegmentedStore();
  await save(store, { classifier: new WordRuleClassifier() });
  assert.deepStrictEqual([...new Set(store.sent)].sort(), ["get kb=1", "set kb=1"]);
});

test("a new version does not meet the old answers", async () => {
  const store = new SegmentedStore();
  await save(store, { classifier: new WordRuleClassifier() });
  const same = await sessionOn(store, { classifier: new WordRuleClassifier() }).decide("what are your opening hours on sunday");
  assert.strictEqual(same.action, "serve");
  const newer = sessionOn(store, { classifier: new WordRuleClassifier(), knowledgeVersion: "2" });
  assert.strictEqual((await newer.decide("what are your opening hours on sunday")).action, "infer");
});

test("the same segment without an understander", async () => {
  const store = new SegmentedStore();
  await save(store);
  assert.deepStrictEqual([...new Set(store.sent)].sort(), ["get kb=1", "set kb=1"]);
});

test("voice and chat share one pool in both modes", async () => {
  for (const options of [{}, { classifier: new WordRuleClassifier() }]) {
    const store = new SegmentedStore();
    const voice = sessionOn(store, options);
    await voice.record(await voice.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.");
    const chat = sessionOn(store, { channel: "chat", ...options });
    assert.strictEqual((await chat.decide("what are your opening hours on sunday")).action, "serve");
  }
});

test("the segment cannot be broken", () => {
  assert.strictEqual(new KnowledgeSegment("2").segment, "kb=2");
  assert.strictEqual(new KnowledgeSegment("v1;x=y").segment, "kb=v1_x_y");
});

const QUESTION = "what are your opening hours on sunday";

test("must still work: voice with stated facts does not share", async () => {
  const session = sessionOn(new SegmentedStore(), { classifier: new WordRuleClassifier() });
  assert.notStrictEqual((await session.decide(QUESTION)).messages, null);
  await session.decide("i am allergic to peanuts");
  assert.strictEqual((await session.decide(QUESTION)).messages, null);
});
