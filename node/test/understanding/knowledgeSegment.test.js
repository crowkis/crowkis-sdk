"use strict";

// v4 P5 item 5: with an understander, voice answers live in kb=<version>;channel=<name>, so switching
// understanders or knowledge is a deliberate new version. Without one, nothing is sent (as before). The
// same cases as python/tests/understanding/test_knowledge_segment.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { KnowledgeSegment } = require("../../src/keys/knowledgeSegment.js");
const { REALTIME, VOICE } = require("../../src/turns/channel.js");
const { WordRuleClassifier } = require("../../src/understanding/wordRuleClassifier.js");
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
  assert.deepStrictEqual([...new Set(store.sent)].sort(), ["get kb=1;channel=voice", "set kb=1;channel=voice"]);
});

test("a new version does not meet the old answers", async () => {
  const store = new SegmentedStore();
  await save(store, { classifier: new WordRuleClassifier() });
  const same = await sessionOn(store, { classifier: new WordRuleClassifier() }).decide("what are your opening hours on sunday");
  assert.strictEqual(same.action, "serve");
  const newer = sessionOn(store, { classifier: new WordRuleClassifier(), knowledgeVersion: "2" });
  assert.strictEqual((await newer.decide("what are your opening hours on sunday")).action, "infer");
});

test("must still work: without an understander no segment is sent", async () => {
  const store = new SegmentedStore();
  await save(store);
  assert.deepStrictEqual([...new Set(store.sent)].sort(), ["get null", "set null"]);
});

test("the segment names the channel and cannot be broken", () => {
  assert.strictEqual(new KnowledgeSegment("2", REALTIME).segment, "kb=2;channel=realtime");
  assert.strictEqual(new KnowledgeSegment("v1;x=y", VOICE).segment, "kb=v1_x_y;channel=voice");
});
