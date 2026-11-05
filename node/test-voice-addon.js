"use strict";
// Server-free tests for the Voice add-on in the SDK: the server's audio cache,
// the fallback to the free basic path, clips stored without holding the
// caller, and voice counts reported to the Voice page. Run: node --test test-voice-addon.js
const test = require("node:test");
const assert = require("node:assert");
const { Agent, waitForAudioStores } = require("./agent.js");
const { VoiceSession } = require("./voice.js");

const ADDON_MISSING = "ENTERPRISE Voice is an add-on to Crowkis Enterprise. Get a licence key that includes it";

class AudioClient {
  constructor({ addon = true, storeDelayMs = 0 } = {}) {
    Object.assign(this, { addon, storeDelayMs, clips: new Map(), tools: new Map(), reports: [], calls: [], failReports: false });
  }
  async caudioget(answer, voice, language, speed, format, { tenant } = {}) {
    this.calls.push("caudioget");
    if (!this.addon) throw new Error(ADDON_MISSING);
    return this.clips.get(JSON.stringify([tenant, answer, voice, language, speed, format])) || null;
  }
  async caudioset(answer, voice, language, speed, format, audio, { ex, ms, tenant } = {}) {
    await new Promise((r) => setTimeout(r, this.storeDelayMs));
    this.calls.push(["caudioset", ex, ms]);
    this.clips.set(JSON.stringify([tenant, answer, voice, language, speed, format]), Buffer.from(audio));
  }
  async ctoolget(tool, args) { this.calls.push("ctoolget"); return this.tools.get(tool + args) || null; }
  async ctoolset(tool, args, result) { this.calls.push("ctoolset"); this.tools.set(tool + args, Buffer.from(result)); }
  async cvoicestat(counts) {
    if (!this.addon) throw new Error(ADDON_MISSING);
    if (this.failReports) throw new Error("connection reset");
    this.reports.push({ ...counts });
  }
}

test("the add-on cache is used, and only for the same sound", async () => {
  const client = new AudioClient();
  const agent = new Agent("bot", { client });
  const made = [];
  const synth = async (text) => { made.push(text); return Buffer.from([0, 1, 2]); };
  const speak = (opts) => agent.speak("We open at nine.", synth, { voice: "aria", ttl: 60, audioFormat: "pcm16-24000", ...opts });
  assert.deepStrictEqual(await speak({ bytesPerSecond: 48000 }), Buffer.from([0, 1, 2]));
  await waitForAudioStores();
  assert.deepStrictEqual(await speak({}), Buffer.from([0, 1, 2]));
  assert.strictEqual(made.length, 1, "replayed, not synthesised again");
  for (const other of [{ audioFormat: "pcm16-16000" }, { language: "fr" }, { speed: "1.25" }]) await speak(other);
  assert.strictEqual(made.length, 4, "another format, language or speed is never reused");
  assert.ok(!client.calls.includes("ctoolset"));
});

test("without the add-on the basic path is used and v2 is not asked again", async () => {
  const client = new AudioClient({ addon: false });
  const agent = new Agent("bot", { client });
  const synth = async () => Buffer.from("audio");
  await agent.speak("Hello there.", synth, { voice: "aria" });
  await agent.speak("Hello there.", synth, { voice: "aria" });
  assert.strictEqual(client.calls.filter((c) => c === "caudioget").length, 1);
  assert.strictEqual(agent.audioHits, 1, "the basic path still reuses the clip");
});

test("any other error is not swallowed", async () => {
  const client = new AudioClient();
  client.caudioget = async () => { throw new Error("tenant is paused"); };
  const agent = new Agent("bot", { client });
  await assert.rejects(agent.speak("Hello there.", async () => Buffer.from("a"), { voice: "aria" }), /paused/);
});

test("the caller never waits for a clip to be stored", async () => {
  const client = new AudioClient({ storeDelayMs: 500 });
  const agent = new Agent("bot", { client });
  const started = Date.now();
  const audio = await agent.speak("A long answer.", async () => Buffer.from("audio"), { voice: "aria" });
  assert.ok(Date.now() - started < 100, `speak waited ${Date.now() - started} ms`);
  assert.deepStrictEqual(audio, Buffer.from("audio"));
  await waitForAudioStores();
  assert.strictEqual(client.clips.size, 1);
});

test("reports send what is new and lose nothing when one fails", async () => {
  const client = new AudioClient();
  const session = new VoiceSession(new Agent("bot", { client }), { voice: "aria" });
  Object.assign(session, { served: 3, inferred: 2, filled: 1, bargeIns: 4 });
  assert.strictEqual(await session.reportStats(), true);
  assert.deepStrictEqual(client.reports.at(-1), { turns: 6, served_from_cache: 3, filler_hits: 1, model_calls_avoided: 4, barge_ins: 4 });
  session.served += 2;
  client.failReports = true;
  await assert.rejects(session.reportStats());
  client.failReports = false;
  assert.strictEqual(await session.reportStats(), true);
  assert.deepStrictEqual(client.reports.at(-1), { turns: 2, served_from_cache: 2, model_calls_avoided: 2 });
  const without = new VoiceSession(new Agent("bot", { client: new AudioClient({ addon: false }) }), { voice: "aria" });
  without.served = 1;
  assert.strictEqual(await without.reportStats(), false);
});

test("odd input goes the basic way, the buffer is copied, no add-on is asked again later", async () => {
  const client = new AudioClient();
  const agent = new Agent("bot", { client });
  await agent.speak("Hello.", async () => Buffer.from("a"), { voice: "v".repeat(65) });
  assert.ok(!client.calls.includes("caudioget") && client.calls.includes("ctoolset"));
  const reused = Buffer.from("original");
  await agent.speak("Copy me.", async () => reused, { voice: "aria" });
  reused.fill(0);
  await waitForAudioStores();
  assert.deepStrictEqual([...client.clips.values()].at(-1), Buffer.from("original"), "stored as synthesised");
  const later = new AudioClient({ addon: false });
  const a2 = new Agent("bot", { client: later });
  await a2.speak("Hi there.", async () => Buffer.from("a"), { voice: "aria" });
  later.addon = true;
  a2._audioV2RecheckAt = Date.now() - 1;
  await a2.speak("New one.", async () => Buffer.from("a"), { voice: "aria" });
  assert.strictEqual(a2._audioV2, true);
});

// S12: on a server that holds answers until it judges them, a served answer's audio.
class HoldingClient extends AudioClient {
  constructor({ vouched = false, engine = true } = {}) {
    super();
    Object.assign(this, { vouched, engine });
  }
  async cgetHit() {
    return { response: Buffer.from("The capital of France is Paris."), similarity: 1, confidence: 0.99, hitType: "exact", vouched: this.vouched };
  }
  async cdecision() {
    this.calls.push("cdecision");
    return { engine: this.engine, holds: this.engine, pending: !this.vouched };
  }
}
const ANSWER = "The capital of France is Paris.";
const TURN = "what is the capital of france";
function holdingCallers(options) {
  const client = new HoldingClient(options);
  const spoken = [];
  const synthesise = async (text) => { spoken.push(text); return Buffer.from("WAV:" + text); };
  const callers = [0, 1].map(() => new VoiceSession(new Agent("caller", { client }), { voice: "alloy", synthesise }));
  return { client, spoken, callers };
}
const stored = (client) => client.calls.filter((c) => Array.isArray(c) && c[0] === "caudioset").length;

test("S12: unjudged audio never reaches another caller", async () => {
  const { client, spoken, callers: [a, b] } = holdingCallers();
  const first = await a.decide(TURN);
  const second = await b.decide(TURN);
  await waitForAudioStores();
  assert.deepStrictEqual([first.action, second.action], ["serve", "serve"]);
  assert.strictEqual(stored(client), 0, "nothing in the shared audio before the verdict");
  assert.strictEqual(spoken.length, 2, "the second caller gets fresh speech, not the first one's clip");
  assert.strictEqual(first.audioShareable, false);
});

test("S12: the same caller replays its own clip before the verdict", async () => {
  const { spoken, callers: [a] } = holdingCallers();
  const first = await a.decide(TURN);
  const again = await a.decide(TURN);
  assert.deepStrictEqual([first.audio, again.audio], [Buffer.from("WAV:" + ANSWER), Buffer.from("WAV:" + ANSWER)]);
  assert.strictEqual(spoken.length, 1);
});

test("S12: once judged the held clip is shared without speaking again", async () => {
  const { client, spoken, callers: [a, b] } = holdingCallers();
  await a.decide(TURN);
  client.vouched = true;
  const cleared = await a.decide(TURN);
  await waitForAudioStores();
  assert.strictEqual(cleared.audioShareable, true);
  assert.strictEqual(stored(client), 1);
  assert.deepStrictEqual((await b.decide(TURN)).audio, Buffer.from("WAV:" + ANSWER));
  assert.strictEqual(spoken.length, 1, "one synthesis for the whole exchange");
  assert.strictEqual(b.agent.audioHits, 1);
});

test("S12: must still work without an engine or once vouched", async () => {
  for (const options of [{ engine: false }, { vouched: true }]) {
    const { client, spoken, callers: [a, b] } = holdingCallers(options);
    assert.strictEqual((await a.decide(TURN)).audioShareable, true);
    await waitForAudioStores();
    await b.decide(TURN);
    assert.deepStrictEqual([spoken.length, b.agent.audioHits, stored(client)], [1, 1, 1], JSON.stringify(options));
  }
});

test("S12: an app that speaks itself is told unjudged audio is not shareable", async () => {
  // No synthesiser: decide() does not ask the server; audioShareable uses what the agent knows.
  for (const [options, shareable] of [[{}, false], [{ vouched: true }, true], [{ engine: false }, true]]) {
    const client = new HoldingClient(options);
    const agent = new Agent("caller", { client });
    await agent.decides();
    const decision = await new VoiceSession(agent, { voice: "alloy" }).decide(TURN);
    assert.strictEqual(decision.action, "serve");
    assert.strictEqual(decision.audioShareable, shareable, JSON.stringify(options));
  }
});
