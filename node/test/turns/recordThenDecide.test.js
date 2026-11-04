"use strict";

// v4 P1 review: record() and the next decide() started in the same tick keep their order. The
// save chains run without a break up to the transcript, as before the rule chains, so a turn
// decided meanwhile, then talked over, never trims the earlier turn out of the call.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../src/client/agent.js");
const { VoiceSession } = require("../../src/channels/voiceSession.js");

class MissingStore {
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

test("a turn recorded while the next one is decided stays in the call when that one is talked over", async () => {
  const session = new VoiceSession(new Agent("caller", { client: new MissingStore() }), { voice: "v" });
  const first = await session.decide("what are your opening hours on weekdays");
  const recorded = session.record(first, "We are open nine to five on weekdays.");
  await session.decide("do you deliver to the north side of town");
  session.cancel();
  await recorded;
  assert.deepStrictEqual(session.transcript.map((turn) => turn.content), [
    "what are your opening hours on weekdays",
    "We are open nine to five on weekdays.",
  ]);
});

test("an empty answer is not keyed: the key is worked out only for an answer", async () => {
  const session = new VoiceSession(new Agent("caller", { client: new MissingStore() }), { voice: "v" });
  const decision = await session.decide("what are your opening hours on weekdays");
  let keyed = 0;
  const contextKey = session._call.contextKey.bind(session._call);
  session._call.contextKey = (...args) => {
    keyed += 1;
    return contextKey(...args);
  };
  await session.record(decision, "");
  assert.strictEqual(keyed, 0);
});

test("must still work: a confident hit is served after the chains", async () => {
  const store = new MissingStore();
  store.cgetHit = async () => ({
    response: Buffer.from("Nine to five."), text: "Nine to five.", similarity: 0.99, ttlRemaining: 600,
    matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "exact",
  });
  const decision = await new VoiceSession(new Agent("caller", { client: store }), { voice: "v" })
    .decide("what are your opening hours on weekdays");
  assert.strictEqual(decision.action, "serve");
});
