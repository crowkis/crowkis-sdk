"use strict";

// v4 P4 step 4: BudgetedUnderstanding. A late or failed model means the word rules read the turn and
// it keeps the caller's words; the turn is counted and logged without its words. The same cases as
// python/tests/understanding/test_budgeted_understanding.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

const BUDGET_MS = 50;

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

// A model that answers only after the test lets it.
class Slow {
  constructor() {
    this.released = new Promise((resolve) => {
      this.release = resolve;
    });
  }

  async classify() {
    await this.released;
    return { isPersonal: false, isContextDependent: false };
  }

  rewrite() {
    return "what is the refund policy";
  }
}

class Broken {
  async classify() {
    throw new TypeError("provider down");
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

function captureWarnings(t) {
  const warnings = [];
  t.mock.method(console, "warn", (message) => warnings.push(String(message)));
  return warnings;
}

test("a late model leaves the turn to the word rules", async (t) => {
  captureWarnings(t);
  const store = new Store();
  store.shared.set("what is the refund policy", "Refunds take five business days.");
  const slow = new Slow();
  t.after(() => slow.release());
  const session = sessionOn(store, { classifier: slow, rewriter: slow, understandBudgetMs: BUDGET_MS });
  const decision = await session.decide("can you tell me about your refund policy");
  assert.strictEqual(decision.action, "infer");
  assert.strictEqual(session.stats().understandTimeouts, 1);
  assert.strictEqual(session.stats().understandErrors, 0);
});

test("a failed model leaves the turn to the word rules and logs no words", async (t) => {
  const warnings = captureWarnings(t);
  const session = sessionOn(new Store(), { classifier: new Broken(), understandBudgetMs: BUDGET_MS });
  const decision = await session.decide("my order 48213 has not arrived where is it");
  assert.strictEqual(decision.rule, "OwnRecords");
  assert.strictEqual(session.stats().understandErrors, 1);
  assert.strictEqual(warnings.join("\n").includes("48213"), false);
  assert.ok(warnings.join("\n").includes("TypeError"));
});

test("a model in time reads and rewrites the turn", async () => {
  const store = new Store();
  store.shared.set("what is the refund policy", "Refunds take five business days.");
  const session = sessionOn(store, { rewriter: new Rewords(), understandBudgetMs: BUDGET_MS * 20 });
  assert.strictEqual((await session.decide("can you tell me about your refund policy")).action, "serve");
  assert.strictEqual(session.stats().understandTimeouts, 0);
});

test("must still work: no model, no budget, no new counts", () => {
  const stats = sessionOn(new Store(), { understandBudgetMs: BUDGET_MS }).stats();
  assert.strictEqual("understandTimeouts" in stats, false);
  assert.strictEqual("understandErrors" in stats, false);
});

// Changed by the P4 review: a model without a budget used to run with no error boundary.
test("no budget runs the model without a deadline inside its error boundary", async () => {
  const store = new Store();
  store.shared.set("what is the refund policy", "Refunds take five business days.");
  const session = sessionOn(store, { rewriter: new Rewords() });
  assert.strictEqual((await session.decide("can you tell me about your refund policy")).action, "serve");
  assert.strictEqual(session.stats().understandErrors, 0);
});

test("the budget must be positive", () => {
  for (const budget of [0, -1]) {
    assert.throws(() => sessionOn(new Store(), { rewriter: new Rewords(), understandBudgetMs: budget }));
  }
});
