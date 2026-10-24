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

// This test used to assert the error was raised, which ended a live turn over the
// audio cache (fixed in Phase 1, step 6). It is now a miss: the clip is made, nothing
// is stored, and the failure is counted.
test("any other error is a miss and never ends the turn", async () => {
  const client = new AudioClient();
  client.caudioget = async () => { throw new Error("tenant is paused"); };
  const agent = new Agent("bot", { client });
  assert.strictEqual(String(await agent.speak("Hello there.", async () => Buffer.from("a"), { voice: "aria" })), "a");
  assert.strictEqual(agent.audioErrors, 1);
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
