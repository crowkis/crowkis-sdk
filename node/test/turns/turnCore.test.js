"use strict";

// v4 P2: TurnCore runs the steps it is given, the same cases as python/tests/turns/test_turn_core.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");
const { RuleSet } = require("../../src/rules/ruleSet.js");
const { SessionHost } = require("../../src/turns/sessionHost.js");
const { TurnCore } = require("../../src/turns/turnCore.js");

class Store {
  constructor() {
    this.shared = new Map();
    this.writes = [];
  }

  async cgetHit(query) {
    const found = this.shared.get(query);
    return found === undefined ? null : {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    this.writes.push([query, response, Boolean(options.template)]);
    this.shared.set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const sessionOn = (store) => new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });

function coreWithout(session, names) {
  return new TurnCore(new SessionHost(session), {
    rules: RuleSet.voice().without(names), call: session._call, pairing: session._pairing,
    cacheLookup: session._cacheLookup, classifier: session._classifier, rewriter: session._rewriter,
    callReadings: session._callReadings, stats: session._stats,
  });
}

test("the rules it is given decide the turn", async () => {
  assert.strictEqual((await sessionOn(new Store()).decide("do you deliver on")).rule, "CutOff");
  const decision = await coreWithout(sessionOn(new Store()), ["CutOff"]).decide("do you deliver on");
  assert.strictEqual(decision.rule, "ConfidenceBar");
});

test("record pairs the answer with its turn", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const core = coreWithout(session, []);
  session._pairing.offer(session._pairing.begin(), true);
  const recorded = await core.record("what is your refund policy", "Refunds take five days.");
  assert.strictEqual(recorded.outcome, "saved");
  assert.deepStrictEqual(store.writes, [["what is your refund policy", "Refunds take five days.", false]]);
});
