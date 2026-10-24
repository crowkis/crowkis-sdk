"use strict";

// A slow server must not stall a turn after a miss. With a latency budget (voiceSession():
// 250 ms) the turn waits for the new answer's write no longer than twice the budget; the write
// finishes in the background ("slow_write", not reported as saved). A clip is stored in
// the background. Without a budget (new VoiceSession(...) as before) the write is waited
// for. Agent.speak() is unchanged. Mirrors python/tests/test_voice_slow_writes.py.
const assert = require("node:assert");
const { test, beforeEach } = require("node:test");
const { Agent, waitForAudioStores } = require("./agent.js");
const { VoiceSession, voiceSession, _waitForWrites, _setWritesMax } = require("./voice.js");
const { AudioClips } = require("./voiceTurns.js");

const QUESTION = "what is your refund policy";
const ANSWER = "Refunds take five business days.";
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

class Store {
  constructor({ writeMs = 1000, failWrite = false, failClip = false } = {}) {
    Object.assign(this, { writeMs, failWrite, failClip });
    this.shared = new Map();
    this.writes = [];
    this.toolWrites = [];
  }
  async cgetHit() { return null; }
  async cset(query, response, options = {}) {
    await sleep(this.writeMs);
    if (this.failWrite) throw new Error("refused");
    this.writes.push([query, response, Boolean(options.template)]);
  }
  async ctoolget() { return null; }
  async ctoolset(tool, key, value) {
    await sleep(this.writeMs);
    if (this.failClip) throw new Error("audio cache down");
    this.toolWrites.push([key, value]);
  }
  async close() {}
}

const timed = async (fn) => {
  const started = performance.now();
  const result = await fn();
  return [result, performance.now() - started];
};

beforeEach(async () => {
  await _waitForWrites(); // no other test's slow writes still queued
  await waitForAudioStores();
});

test("with a budget a slow write never holds the turn", async () => {
  const store = new Store();
  const session = voiceSession({ client: store });
  const [decision, ms] = await timed(() => session.answer(QUESTION, async () => ANSWER));
  assert.ok(decision.needsModel);
  assert.ok(ms < 800, `the turn waited for the slow write (${ms} ms); it waits at most twice the budget`);
  assert.strictEqual(decision.stored, false, "not confirmed, so not reported as saved");
  assert.match(decision.notStored, /latency budget/);
  assert.strictEqual(session.slowWrites, 1);
  assert.strictEqual(session.stats().slowWrites, 1);
  await _waitForWrites(); // the write still lands, in the background
  assert.deepStrictEqual(store.writes, [[QUESTION, ANSWER, false]]);
});

test("streaming and record are bounded too", async () => {
  for (const [name, run] of [
    ["respond", async (s) => { const r = await s.respond(QUESTION, async function* () { yield ANSWER; }); for await (const _ of r); }],
    ["record", async (s) => s.record(await s.decide(QUESTION), ANSWER)],
  ]) {
    const session = voiceSession({ client: new Store() });
    const [, ms] = await timed(() => run(session));
    assert.ok(ms < 800, `${name}: ${ms} ms`);
  }
});

test("a late write that fails is counted", async () => {
  const session = voiceSession({ client: new Store({ writeMs: 800, failWrite: true }) });
  await session.answer(QUESTION, async () => ANSWER);
  await _waitForWrites();
  assert.deepStrictEqual([session.slowWrites, session.learnErrors], [1, 1]);
});

test("a hung server never queues writes without limit", async () => {
  let release;
  const hung = new Promise((r) => { release = r; });
  const store = new Store();
  store.cset = () => hung;
  const session = voiceSession({ client: store });
  const restore = _setWritesMax(3);
  const outcomes = [];
  try {
    for (const q of ["what is your refund policy", "how do I reset my password", "what are your opening hours",
      "do you ship to canada", "how do I cancel my plan"]) {
      outcomes.push((await session.answer(q, async () => ANSWER)).notStored);
    }
  } finally {
    restore();
    release();
  }
  assert.strictEqual(session.slowWrites, 5);
  assert.ok(outcomes.slice(0, 3).every((o) => /latency budget/.test(o)), outcomes.join(" | "));
  // Past the cap nothing is written, and the report says so.
  assert.ok(outcomes.slice(3).every((o) => /not written/.test(o) && /too many writes/.test(o)), outcomes.join(" | "));
});

test("a slow template write is not reported as stored", async () => {
  const store = new Store();
  const session = voiceSession({ client: store, values: { order_id: "A-1001", eta: "Tuesday" }, shareTemplates: true });
  const decision = await session.answer("when will i get my order", async () => "Your order A-1001 is due to arrive on Tuesday.");
  assert.strictEqual(decision.stored, false);
  assert.match(decision.notStored, /latency budget/);
  assert.strictEqual(session.slowWrites, 1);
  await _waitForWrites();
  assert.deepStrictEqual(store.writes, [["when will i get my order", "Your order {order_id} is due to arrive on {eta}.", true]]);
});

test("must still work: a quick template write is a template", async () => {
  const store = new Store({ writeMs: 0 });
  const session = voiceSession({ client: store, values: { order_id: "A-1001", eta: "Tuesday" }, shareTemplates: true });
  const decision = await session.answer("when will i get my order", async () => "Your order A-1001 is due to arrive on Tuesday.");
  assert.strictEqual(decision.stored, true);
  assert.strictEqual(session.slowWrites, 0);
});

test("a write within the budget is reported as before", async () => {
  const session = voiceSession({ client: new Store({ writeMs: 0, failWrite: true }) });
  const decision = await session.answer(QUESTION, async () => ANSWER);
  assert.match(decision.notStored, /refused/);
  assert.deepStrictEqual([session.slowWrites, session.learnErrors], [0, 1]);
});

test("must still work: without a budget the write is waited for", async () => {
  const store = new Store({ writeMs: 400 });
  const session = new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });
  const [, ms] = await timed(() => session.answer(QUESTION, async () => ANSWER));
  assert.ok(ms >= 390, `${ms} ms`);
  assert.deepStrictEqual(store.writes, [[QUESTION, ANSWER, false]]);
  assert.strictEqual(session.slowWrites, 0);
});

test("an audio clip is stored in the background", async () => {
  const store = new Store();
  const session = voiceSession({ client: store, voice: "v" });
  const clips = new AudioClips(session, 16000);
  const [, ms] = await timed(() => clips._store(ANSWER, Buffer.alloc(320, 1)));
  assert.ok(ms < 300, `${ms} ms`);
  await waitForAudioStores();
  assert.strictEqual(store.toolWrites.length, 1);
});

test("a clip store that fails in the background is counted", async () => {
  const session = voiceSession({ client: new Store({ writeMs: 0, failClip: true }), voice: "v" });
  await new AudioClips(session, 16000)._store(ANSWER, Buffer.alloc(320, 1));
  await waitForAudioStores();
  assert.strictEqual(session.agent.audioErrors, 1);
});
