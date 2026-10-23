"use strict";

// v4 P4 step 2: a session uses the classifier and rewriter it is given (defaults: the word rules,
// no rewrite). The same cases as python/tests/understanding/test_slots_wired.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { CrowkisClient } = require("../../index.js");
const { BudgetedUnderstanding } = require("../../src/understanding/budgetedUnderstanding.js");
const { WordRuleClassifier } = require("../../src/understanding/wordRuleClassifier.js");
const { VoiceSession, voiceSession } = require("../../src/channels/voiceSession.js");

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

// The word rules, except that one turn is read as personal.
class ReadsPersonal {
  constructor(personalTurn) {
    this._personalTurn = personalTurn;
  }

  classify(text) {
    const reading = new WordRuleClassifier().classify(text);
    if (text !== this._personalTurn) return reading;
    return { isPersonal: true, isContextDependent: reading.isContextDependent };
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
  // The factory gives a plugged-in model the understanding budget (P4 step 4).
  assert.ok(session._classifier instanceof BudgetedUnderstanding);
  assert.strictEqual(session._rewriter, session._classifier);
  assert.strictEqual(session._classifier._classifier, classifier);
  assert.strictEqual(session._classifier._rewriter, rewriter);
});

test("a turn the classifier reads personal is never shared", async () => {
  const store = new Store();
  const session = sessionOn(store, { classifier: new AlwaysPersonal() });
  const decision = await session.decide("what is your refund policy");
  assert.strictEqual(decision.messages, null);
  assert.strictEqual(decision.cacheable, false);
  await session.record(decision, "Refunds take five business days.");
  assert.strictEqual(store.shared.has("what is your refund policy"), false);
});

test("a follow-up to a turn the classifier read personal is private", async () => {
  const session = sessionOn(new Store(), { classifier: new ReadsPersonal("what does the gold plan cost") });
  await session.record(await session.decide("what does the gold plan cost"), "The gold plan costs 499 a month.");
  const decision = await session.decide("and how long will that take");
  assert.strictEqual(decision.rule, "PrivateChain");
  assert.strictEqual(decision.cacheable, false);
});

test("must still work: a follow-up to a general turn is shared", async () => {
  const session = sessionOn(new Store(), { classifier: new ReadsPersonal("something else entirely") });
  await session.record(await session.decide("what does the gold plan cost"), "The gold plan costs 499 a month.");
  assert.strictEqual((await session.decide("and how long will that take")).cacheable, true);
});

test("must still work: the defaults are the word rules", async () => {
  const decision = await sessionOn(new Store()).decide("what is your refund policy");
  assert.strictEqual(decision.rule, "ConfidenceBar");
});
