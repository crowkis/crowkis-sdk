"use strict";

// v4 P4 step 2: a session uses the classifier and rewriter it is given (defaults: the word rules,
// no rewrite). The same cases as python/tests/understanding/test_slots_wired.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { CrowkisClient } = require("../../index.js");
const { VoiceSession, voiceSession } = require("../../voice.js");

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

class AlwaysPersonal {
  classify() {
    return { isPersonal: true, isContextDependent: false };
  }
}

class Rewords {
  rewrite() {
    return "what is the refund policy";
  }
}

function sessionOn(store, options = {}) {
  return new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });
}

test("a plugged-in classifier reads the turn", async () => {
  const decision = await sessionOn(new Store(), { classifier: new AlwaysPersonal() }).decide("what is your refund policy");
  assert.strictEqual(decision.rule, "OwnRecords");
});

test("a plugged-in rewriter keys the lookup", async () => {
  const store = new Store();
  store.shared.set("what is the refund policy", "Refunds take five business days.");
  const decision = await sessionOn(store, { rewriter: new Rewords() }).decide("whats ur refund policy pls");
  assert.strictEqual(decision.action, "serve");
});

test("the factory passes them through", () => {
  const classifier = new AlwaysPersonal();
  const rewriter = new Rewords();
  const session = voiceSession({ client: new CrowkisClient({ port: 1 }), classifier, rewriter });
  assert.strictEqual(session._classifier, classifier);
  assert.strictEqual(session._rewriter, rewriter);
});

test("must still work: the defaults are the word rules", async () => {
  const decision = await sessionOn(new Store()).decide("what is your refund policy");
  assert.strictEqual(decision.rule, "ConfidenceBar");
});
