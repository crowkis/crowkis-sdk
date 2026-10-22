"use strict";

// v4 P2 cleanup: Stats keeps the session's counters, the same cases as python/tests/runtime/test_stats.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("../../agent.js");
const { VoiceSession } = require("../../voice.js");
const { COUNTER, Stats } = require("../../src/runtime/stats.js");

test("counters start at zero and add", () => {
  const stats = new Stats();
  stats.add(COUNTER.FILLED);
  stats.add(COUNTER.FILLED);
  assert.strictEqual(stats.get(COUNTER.FILLED), 2);
  stats.countRule("CutOff");
  assert.deepStrictEqual(stats.ruleCounts(), { CutOff: 1 });
});

test("the session counters are the stats", async () => {
  const client = { cgetHit: async () => null, cset: async () => {}, ctoolget: async () => null, ctoolset: async () => {}, close: async () => {} };
  const session = new VoiceSession(new Agent("caller", { client }), { voice: "v" });
  session.bargeIns += 1;
  assert.strictEqual(session._stats.get(COUNTER.BARGE_INS), 1);
  await session.decide("do you deliver on");
  assert.deepStrictEqual([session.refusedShort, session.stats().rules], [1, { CutOff: 1 }]);
});
