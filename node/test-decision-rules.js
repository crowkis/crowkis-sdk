"use strict";

// v4 P0: every voice decision names the rule that made it (fixtures/decision-rules.json),
// the same cases as python/tests/test_decision_rules.py. `decision.rule` is the question
// or hit rule behind decide()'s action and `decision.saveRule` the save rule behind
// record()'s outcome. Both are added fields: action, reason, stored and notStored are unchanged.

const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { Agent } = require("./src/client/agent.js");
const { VoiceSession } = require("./src/channels/voiceSession.js");

const FIXTURE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "decision-rules.json"), "utf8"));

// The server: shared answers matched on the exact key; `refuse` fails every write.
class Store {
  constructor(refuse = null) {
    this.shared = new Map();
    this.templates = new Map();
    this.refuse = refuse;
  }

  async cgetHit(query, options = {}) {
    const found = (options.template ? this.templates : this.shared).get(query);
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    if (this.refuse) throw this.refuse;
    (options.template ? this.templates : this.shared).set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

// The fixture names VoiceSession's options as Python does.
const OPTION_NAMES = { share_templates: "shareTemplates", short_turns: "shortTurns" };
const BUDGET_MS = 50;
const SLOW_SERVER_MS = 500;

function nodeOptions(options = {}) {
  return Object.fromEntries(Object.entries(options).map(([name, value]) => [OPTION_NAMES[name] || name, value]));
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

function sessionOn(store, options = {}) {
  return new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });
}

async function lastDecision(testCase) {
  const store = new Store(testCase.refuse ? new Error("write refused") : null);
  const session = sessionOn(store, nodeOptions(testCase.options));
  const last = testCase.turns.length - 1;
  let decision = null;
  for (let index = 0; index <= last; index += 1) {
    decision = await session.decide(testCase.turns[index]);
    if (decision.needsModel) {
      const isLast = index === last;
      decision = await session.record(decision, testCase.replies[index], {
        private: Boolean(testCase.private) && isLast,
        system: isLast && testCase.system ? testCase.system : null,
      });
    }
  }
  return decision;
}

for (const testCase of FIXTURE.cases) {
  test(`decision rules: ${testCase.name}`, async () => {
    const decision = await lastDecision(testCase);
    assert.strictEqual(decision.action, testCase.action || "infer");
    assert.strictEqual(decision.rule, testCase.rule);
    assert.strictEqual(decision.saveRule, testCase.save_rule);
  });
}

test("a new decision names no save rule yet", async () => {
  const decision = await sessionOn(new Store()).decide("what is your refund policy");
  assert.strictEqual(decision.saveRule, null);
});

test("a turn talked over is interrupted", async () => {
  const session = sessionOn(new Store());
  let decision = await session.decide("what is your refund policy");
  session.cancel();
  decision = await session.record(decision, "Refunds take five business days.");
  assert.strictEqual(decision.saveRule, "Interrupted");
});

test("the hit guards are named", async () => {
  const store = new Store();
  store.shared.set("what is your refund policy", "See https://example.com/refunds for details.");
  const decision = await sessionOn(store).decide("what is your refund policy");
  assert.deepStrictEqual([decision.action, decision.rule], ["infer", "ScreenOnlyAnswer"]);
});

test("a late lookup is named", async () => {
  const store = new Store();
  const lookup = store.cgetHit.bind(store);
  store.cgetHit = async (...args) => {
    await sleep(SLOW_SERVER_MS);
    return lookup(...args);
  };
  const decision = await sessionOn(store, { latencyBudgetMs: BUDGET_MS }).decide("what is your refund policy");
  assert.strictEqual(decision.rule, "LookupDeadline");
});

test("a write past the budget is named", async () => {
  const store = new Store();
  const write = store.cset.bind(store);
  store.cset = async (...args) => {
    await sleep(SLOW_SERVER_MS);
    return write(...args);
  };
  const session = sessionOn(store, { latencyBudgetMs: BUDGET_MS });
  const decision = await session.record(await session.decide("what is your refund policy"), "Refunds take five business days.");
  assert.strictEqual(decision.saveRule, "BoundedWrite");
  await sleep(SLOW_SERVER_MS);
});

test("a streamed answer talked over is interrupted", async () => {
  const session = sessionOn(new Store());
  const response = await session.respond("what is your refund policy", () => ["Refunds take ", "five days."]);
  for await (const _ of response) session.cancel();
  assert.strictEqual(response.decision.saveRule, "Interrupted");
});

test("an unreachable cache is named", async () => {
  const store = new Store();
  store.cgetHit = async () => { throw new Error("down"); };
  const decision = await sessionOn(store).decide("what is your refund policy");
  assert.strictEqual(decision.rule, "CacheUnavailable");
});
