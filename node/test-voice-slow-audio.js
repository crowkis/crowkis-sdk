"use strict";
// A hung audio cache never holds a cache hit (K4). As in python/tests/test_voice_slow_audio.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, voiceSession } = require("./voice.js");

const QUESTION = "what is your refund policy";
const ANSWER = "Refunds take five business days.";
const PCM = Buffer.alloc(320, 1);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class SlowAudio {
  constructor(ms) { this.ms = ms; this.tool = new Map(); }
  async cgetHit(query) {
    if (query !== QUESTION) return null;
    return { response: Buffer.from(ANSWER), text: ANSWER, similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }
  async cset() {}
  async ctoolget(tool, key) { await sleep(this.ms); return this.tool.get(key) || null; }
  async ctoolset(tool, key, value) { this.tool.set(key, value); }
  async close() {}
}

const timed = async (session) => {
  const started = performance.now();
  const decision = await session.decide(QUESTION);
  return [decision, performance.now() - started];
};

test("a hung audio read never holds a hit", async () => {
  const session = voiceSession({ client: new SlowAudio(1500), voice: "v", synthesise: async () => PCM });
  const [decision, ms] = await timed(session);
  assert.deepStrictEqual([decision.action, decision.text, decision.audio], ["serve", ANSWER, null]);
  assert.ok(ms < 900, `the hit waited for the hung audio read (${ms} ms)`);
  assert.strictEqual(session.audioUnavailable, 1);
});

test("must still work: a quick audio read gives the audio", async () => {
  const session = voiceSession({ client: new SlowAudio(0), voice: "v", synthesise: async () => PCM });
  const [decision] = await timed(session);
  assert.strictEqual(decision.action, "serve");
  assert.ok(Buffer.from(decision.audio).equals(PCM));
  assert.strictEqual(session.audioUnavailable, 0);
});

test("must still work: without a budget the audio is waited for", async () => {
  const session = new VoiceSession(new Agent("a", { client: new SlowAudio(600) }), { voice: "v", synthesise: async () => PCM });
  const [decision, ms] = await timed(session);
  assert.ok(Buffer.from(decision.audio).equals(PCM));
  assert.ok(ms >= 590, `${ms} ms`);
});
