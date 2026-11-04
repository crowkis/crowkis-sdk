"use strict";

// v4 P4 review fixes: a plugged-in model never makes a call less private. A rewrite is used only for a
// turn that is neither personal nor a follow-up (by its reading or the word rules), only when it adds
// no caller detail, and only for the turn it was made for; a failing model never ends a call. The same
// cases as python/tests/understanding/test_rewrite_safety.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../src/client/agent.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

class Store {
  constructor() {
    this.shared = new Map();
    this.templates = new Map();
    this.reads = [];
  }

  async cgetHit(query, options = {}) {
    this.reads.push(query);
    const found = (options.template ? this.templates : this.shared).get(query);
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    (options.template ? this.templates : this.shared).set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const reads = ({ personal = false, followUp = false } = {}) => ({ isPersonal: personal, isContextDependent: followUp });

class General {
  classify() {
    return reads();
  }
}

// A rewriter that answers from a list, one rewrite per turn (null: no rewrite).
class Script {
  constructor(...rewrites) {
    this._rewrites = rewrites;
  }

  rewrite() {
    return this._rewrites.shift();
  }
}

class Broken {
  classify() {
    throw new RangeError("provider down");
  }
}

function sessionOn(store, options = {}) {
  return new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });
}

function quiet(t) {
  t.mock.method(console, "warn", () => {});
}

test("a repeated turn without a rewrite is saved under its own words", async () => {
  const store = new Store();
  const session = sessionOn(store, { rewriter: new Script("what is the price of the gold plan", null) });
  await session.record(await session.decide("what does the plan cost"), "The gold plan costs 499.");
  await session.record(await session.decide("what does the plan cost"), "The silver plan costs 199.");
  assert.notStrictEqual(store.shared.get("what is the price of the gold plan"), "The silver plan costs 199.");
});

test("a word-rule follow-up stays a follow-up whatever the reading", async () => {
  const flightPersonal = { classify: (text) => reads({ personal: text.includes("flight") }) };
  const session = sessionOn(new Store(), { classifier: flightPersonal });
  await session.record(await session.decide("when does the next flight to delhi leave"), "Your flight leaves at 6 pm.");
  const decision = await session.decide("and how long will that take");
  assert.strictEqual(decision.rule, "PrivateChain");
  assert.strictEqual(decision.cacheable, false);
});

test("a follow-up is never saved under a bare rewrite", async () => {
  const store = new Store();
  const session = sessionOn(store, { classifier: new General(), rewriter: new Script(null, "what are the opening hours") });
  await session.record(await session.decide("tell me about the paris office"), "The Paris office is on Rue Royale.");
  await session.record(await session.decide("and what are its hours"), "The Paris office opens 9 to 5.");
  assert.strictEqual(store.shared.has("what are the opening hours"), false);
});

test("a turn the word rules call personal is never rewritten", async () => {
  const store = new Store();
  const session = sessionOn(store, {
    classifier: new General(), rewriter: new Script("what is the refund policy"),
    values: { order: "48213" }, shareTemplates: true,
  });
  await session.record(await session.decide("where is my order 48213"), "Your order 48213 ships tomorrow.");
  assert.strictEqual(store.reads.includes("what is the refund policy"), false);
  assert.strictEqual(store.templates.has("what is the refund policy"), false);
});

test("a rewrite that adds a detail the caller did not say is dropped", async () => {
  for (const rewrite of ["what are the hours for John Smith on sunday", "what are the hours at 12 elm street",
    "what are the hours for order 48213"]) {
    const store = new Store();
    const session = sessionOn(store, { classifier: new General(), rewriter: new Script(rewrite) });
    await session.record(await session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.");
    assert.strictEqual(store.reads.includes(rewrite), false, rewrite);
    assert.strictEqual(store.shared.has(rewrite), false, rewrite);
  }
});

test("a rewrite that carries a declared value is dropped", async () => {
  const store = new Store();
  const session = sessionOn(store, {
    classifier: new General(), rewriter: new Script("what are the hours for priya"), values: { name: "Priya" },
  });
  await session.decide("what are your opening hours on sunday");
  assert.strictEqual(store.reads.includes("what are the hours for priya"), false);
});

test("a blank rewrite is no rewrite", async () => {
  const store = new Store();
  const session = sessionOn(store, { classifier: new General(), rewriter: new Script("  ") });
  await session.record(await session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.");
  assert.strictEqual(store.shared.has("what are your opening hours on sunday"), true);
});

test("must still work: a safe rewrite is used", async () => {
  const store = new Store();
  const session = sessionOn(store, { classifier: new General(), rewriter: new Script("what are the opening hours on sunday") });
  await session.record(await session.decide("when do you open on sundays"), "We open at 10 on Sundays.");
  assert.strictEqual(store.shared.get("what are the opening hours on sunday"), "We open at 10 on Sundays.");
});

test("a failing model without a budget never ends the call", async (t) => {
  quiet(t);
  const session = sessionOn(new Store(), { classifier: new Broken() });
  const decision = await session.decide("what are your opening hours on sunday");
  assert.strictEqual(decision.action, "infer");
  assert.strictEqual(session.stats().understandErrors, 1);
});

test("no rewrite once the caller has told the call something", async () => {
  // The classifier reads the call's facts, so its rewrite could carry one into a shared key (P5 review).
  const { FrameReading } = require("../../src/understanding/model/frame.js");
  const { TurnFrame } = require("../../src/understanding/model/frame.js");
  const sureTheTripDoesNotMatter = { classify: () => new FrameReading(TurnFrame.fromDict({
    kind: "general", subject: "none", confidence: 0.9, question: "-",
    fact_relevance: [{ fact: "place: goa", type: "trip", changes_answer: false }],
  })) };
  const store = new Store();
  const rewrite = "what are the opening hours for travellers to goa";
  const session = sessionOn(store, { classifier: sureTheTripDoesNotMatter, rewriter: new Script(null, rewrite) });
  await session.record(await session.decide("we are planning a trip to goa next month"), "Have a good trip.");
  assert.strictEqual((await session.decide("what are your opening hours on sunday")).cacheable, true);
  assert.strictEqual(store.reads.includes(rewrite), false);
});

test("a classifier written for classify(text) still reads the turn", async () => {
  const textOnly = { classify: (text) => reads({ personal: true }) };
  const session = sessionOn(new Store(), { classifier: textOnly });
  assert.strictEqual((await session.decide("what are your opening hours on sunday")).rule, "OwnRecords");
  assert.strictEqual(session.stats().understandErrors, 0);
});
