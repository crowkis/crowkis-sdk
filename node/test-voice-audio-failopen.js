"use strict";
// Audio never breaks a call, and a clip is only reused for the sound it was made for
// (same as python/tests/test_voice_audio_failopen.py).
// - Agent.speak(): an audio cache read or write that fails is a miss: the clip is made
//   and returned, the failure logged and counted (agent.audioErrors). Before, a failed
//   read rejected and a failed basic-path write lost the clip just made.
// - VoiceSession: when the audio step fails (the cache, or the app's own synthesiser),
//   the turn still gets its text, with no audio (stats().audioUnavailable).
// - The basic audio cache key names language, speed and format when they are not the
//   defaults; with the defaults it is unchanged, so existing clips stay valid.
const test = require("node:test");
const assert = require("node:assert");
const { Agent, _ttsKey } = require("./agent.js");
const { VoiceSession } = require("./voice.js");

const ANSWER = "Here is the answer.";
const PCM = Buffer.from("pcm-audio");

class AudioServer {
  constructor({ v2 = true, fail = [] } = {}) {
    Object.assign(this, { v2, fail: new Set(fail), tool: new Map(), audio: new Map(), calls: [], shared: new Map() });
  }
  maybeFail(name) {
    this.calls.push(name);
    if (this.fail.has(name)) throw new Error(`ERR ${name} failed: connection reset`);
  }
  async caudioget(text, ...labels) {
    if (!this.v2) {
      this.calls.push("caudioget");
      throw new Error("ENTERPRISE Voice is an add-on to Crowkis Enterprise. Get a licence key that includes it");
    }
    this.maybeFail("caudioget");
    return this.audio.get(JSON.stringify([text, ...labels.slice(0, 4)])) || null;
  }
  async caudioset(text, ...rest) {
    this.maybeFail("caudioset");
  }
  async ctoolget(tool, key) {
    this.maybeFail("ctoolget");
    return this.tool.get(key) ?? null;
  }
  async ctoolset(tool, key, value) {
    this.maybeFail("ctoolset");
    this.tool.set(key, value);
  }
  async cgetHit(query) {
    const found = this.shared.get(query);
    if (found === undefined) return null;
    return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }
  async cset() {}
  async close() {}
}

const synth = async () => PCM;
const broken = async () => {
  throw new Error("TTS down");
};

test("a failed audio cache read is a miss, not an error", async () => {
  const server = new AudioServer({ fail: ["caudioget"] });
  const agent = new Agent("a", { client: server });
  assert.strictEqual(await agent.speak(ANSWER, synth, { voice: "v" }), PCM);
  assert.ok(!server.calls.includes("caudioset"));
  assert.strictEqual(agent.audioErrors, 1);
});

test("a failed basic read is a miss, and a failed basic write still returns the clip", async () => {
  let server = new AudioServer({ v2: false, fail: ["ctoolget"] });
  let agent = new Agent("a", { client: server });
  assert.strictEqual(await agent.speak(ANSWER, synth, { voice: "v" }), PCM);
  assert.ok(!server.calls.includes("ctoolset"));
  assert.strictEqual(agent.audioErrors, 1);
  server = new AudioServer({ v2: false, fail: ["ctoolset"] });
  agent = new Agent("a", { client: server });
  assert.strictEqual(await agent.speak(ANSWER, synth, { voice: "v" }), PCM);
  assert.strictEqual(agent.audioErrors, 1);
});

test("no Voice add-on still uses the basic cache; a synthesiser error is the app's", async () => {
  const server = new AudioServer({ v2: false });
  const agent = new Agent("a", { client: server });
  await agent.speak(ANSWER, synth, { voice: "v" });
  assert.ok(server.calls.includes("ctoolset"));
  assert.strictEqual(String(await agent.speak(ANSWER, broken, { voice: "v" })), String(PCM));
  assert.strictEqual(agent.audioErrors, 0);
  await assert.rejects(new Agent("b", { client: new AudioServer() }).speak("Other.", broken, { voice: "v" }), /TTS down/);
});

test("the default key is unchanged; anything that changes the sound changes the key", () => {
  assert.strictEqual(_ttsKey(ANSWER, ["v", "und", "1", "default"]), JSON.stringify({ text: ANSWER, voice: "v" }));
  const keys = new Set([
    _ttsKey(ANSWER, ["v", "und", "1", "default"]),
    _ttsKey(ANSWER, ["v", "und", "1", "pcm16-8000"]),
    _ttsKey(ANSWER, ["v", "und", "1", "pcm16-24000"]),
    _ttsKey(ANSWER, ["v", "hi", "1", "default"]),
    _ttsKey(ANSWER, ["v", "und", "1.2", "default"]),
  ]);
  assert.strictEqual(keys.size, 5);
});

test("speak reuses a basic clip only for the same format", async () => {
  const agent = new Agent("a", { client: new AudioServer({ v2: false }) });
  await agent.speak(ANSWER, async () => Buffer.from("8k"), { voice: "v", audioFormat: "pcm16-8000" });
  assert.strictEqual(String(await agent.speak(ANSWER, async () => Buffer.from("24k"), { voice: "v", audioFormat: "pcm16-24000" })), "24k");
  assert.strictEqual(String(await agent.speak(ANSWER, broken, { voice: "v", audioFormat: "pcm16-8000" })), "8k");
});

test("a cache hit whose audio fails still serves the text", async () => {
  for (const [server, synthesise] of [
    [new AudioServer({ fail: ["caudioget"] }), broken], // the cache fails, then the TTS too
    [new AudioServer({ v2: false }), broken],           // the app's TTS fails
  ]) {
    server.shared.set("what is your refund policy", ANSWER);
    const session = new VoiceSession(new Agent("a", { client: server }), { voice: "v", synthesise });
    const decision = await session.decide("what is your refund policy");
    assert.deepStrictEqual([decision.action, decision.text, decision.audio], ["serve", ANSWER, null]);
    assert.strictEqual(session.stats().audioUnavailable, 1);
  }
});

test("a filler, answer() and respond() keep working when audio fails", async () => {
  const server = new AudioServer({ v2: false });
  server.shared.set("what is your refund policy", ANSWER);
  const session = new VoiceSession(new Agent("a", { client: server }), {
    voice: "v",
    synthesise: broken,
    fillers: { hello: "Hi, how can I help?" },
  });
  const filler = await session.decide("hello");
  assert.deepStrictEqual([filler.action, filler.text, filler.audio], ["filler", "Hi, how can I help?", null]);
  assert.strictEqual((await session.answer("what is your refund policy", async () => assert.fail("model"))).text, ANSWER);
  const pieces = [];
  for await (const p of await session.respond("what is your refund policy", () => assert.fail("model"))) pieces.push(p);
  assert.deepStrictEqual(pieces, [ANSWER]);
});

test("audio that works is unchanged", async () => {
  const server = new AudioServer({ v2: false });
  server.shared.set("what is your refund policy", ANSWER);
  const session = new VoiceSession(new Agent("a", { client: server }), { voice: "v", synthesise: synth });
  const decision = await session.decide("what is your refund policy");
  assert.strictEqual(decision.audio, PCM);
  assert.strictEqual(session.stats().audioUnavailable, 0);
});
