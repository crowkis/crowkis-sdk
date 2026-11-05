"use strict";

// v4 P5 item 3: the merged save check. Voice with an understander gains PrivateWord and ActionClaim.
// The same cases as
// python/tests/test_merged_save_check.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../src/client/agent.js");
const { WordRuleClassifier } = require("../../src/understanding/slots.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

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

test("voice, F7: the default rules also keep an action claim private", async () => {
  const store = new Store();
  const session = voiceOn(store);
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, "I have cancelled your order and refunded you.");
  assert.strictEqual(decision.saveRule, "VoiceActionClaim");
  assert.strictEqual(store.shared.has("what is your refund policy"), false);
});
