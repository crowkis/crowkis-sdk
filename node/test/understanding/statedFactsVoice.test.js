"use strict";

// v4 P5 item 1: with an understander, StatedFacts replaces the call-wide taint. A later turn is shared
// only when the model is sure no stated fact changes its answer; an allergy, a medication, a pregnancy
// or an age always counts; unsure, late or no model: today's strict rule. The same cases as
// python/tests/understanding/test_stated_facts_voice.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { LLMClassifier, LLMUnderstander } = require("../../index.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

const TRIP_TURN = "we are planning a trip to goa next month with the kids";
const TRIP_FRAME = { kind: "personal", subject: "self", confidence: 0.9,
  entities: [{ text: "trip to goa", type: "place", identifying: false, answer_relevant: true }] };
const DEDUCTIBLE = { kind: "general", subject: "none", confidence: 0.9, question: "-" };

class Store {
  constructor() {
    this.shared = new Map();
  }

  async cgetHit(query) {
    const found = this.shared.get(query);
    if (found === undefined) return null;
    return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
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

// Answers each turn with its scripted frame; remembers the call state it was sent.
class Model {
  constructor(frames) {
    this.frames = frames;
    this.states = [];
    this.complete = async (messages) => {
      const payload = JSON.parse(messages[messages.length - 1].content);
      this.states.push(payload.call_state);
      return JSON.stringify(this.frames[payload.turn] || { kind: "unclear" });
    };
  }
}

function callWith(frames) {
  const model = new Model(frames);
  const store = new Store();
  const session = new VoiceSession(new Agent("caller", { client: store }), {
    voice: "v", classifier: new LLMClassifier(new LLMUnderstander(model.complete)),
  });
  return { model, store, session };
}

const tripRelevance = (changes) => [{ fact: "place: trip to goa", type: "trip", changes_answer: changes }];

test("an unrelated stated fact no longer keeps the call private", async () => {
  const { store, session } = callWith({
    // Each fact of the stated turn (the trip, the kids) needs its own "does not change" (P5 re-check).
    [TRIP_TURN]: TRIP_FRAME, "what is a deductible in insurance": { ...DEDUCTIBLE, fact_relevance: [
      ...tripRelevance(false), { fact: "family: the kids", type: "other", changes_answer: false }] },
  });
  const first = await session.decide(TRIP_TURN);
  assert.strictEqual(first.rule, "VoiceStatedFacts");
  await session.record(first, "Goa is lovely in December.");
  const later = await session.decide("what is a deductible in insurance");
  assert.strictEqual(later.cacheable, true);
  await session.record(later, "A deductible is what you pay before insurance pays.");
  assert.strictEqual(store.shared.has("what is a deductible in insurance"), true);
  assert.strictEqual(store.shared.has(TRIP_TURN), false);
});

test("a relevant stated fact keeps the later turn private", async () => {
  const { store, session } = callWith({
    [TRIP_TURN]: TRIP_FRAME, "how do i file a claim": { ...DEDUCTIBLE, fact_relevance: tripRelevance(true) },
  });
  await session.record(await session.decide(TRIP_TURN), "Goa is lovely in December.");
  const later = await session.decide("how do i file a claim");
  assert.strictEqual(later.rule, "VoiceStatedFacts");
  assert.strictEqual(later.cacheable, false);
  await session.record(later, "Call us with your policy number.");
  assert.strictEqual(store.shared.size, 0);
});

test("an allergy always counts", async () => {
  const { session } = callWith({
    "which desserts do you have today": { ...DEDUCTIBLE,
      fact_relevance: [{ fact: "condition: peanuts", type: "other", changes_answer: false }] },
  });
  await session.record(await session.decide("I am allergic to peanuts"), "Noted.");
  assert.strictEqual((await session.decide("which desserts do you have today")).cacheable, false);
});

test("the model reads the call's facts, never its turns", async () => {
  const { model, session } = callWith({ [TRIP_TURN]: TRIP_FRAME });
  await session.record(await session.decide(TRIP_TURN), "Goa is lovely in December.");
  await session.decide("what is a deductible in insurance");
  assert.deepStrictEqual(model.states[model.states.length - 1].facts, ["place: trip to goa"]);
  assert.strictEqual(JSON.stringify(model.states[model.states.length - 1]).includes("kids"), false);
});

test("must still work: without an understander the call is tainted", async () => {
  const session = new VoiceSession(new Agent("caller", { client: new Store() }), { voice: "v" });
  await session.record(await session.decide(TRIP_TURN), "Goa is lovely in December.");
  const later = await session.decide("what is a deductible in insurance");
  assert.strictEqual(later.rule, "CallContextTaint");
  assert.strictEqual(later.cacheable, false);
});
