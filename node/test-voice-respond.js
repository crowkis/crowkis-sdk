"use strict";
// VoiceSession.respond(): the text to speak, piece by piece, as the model writes it
// (same as python/tests/test_voice_respond.py). It decides at once (stream.decision is
// ready before the first piece). A cache or filler turn yields that text and never
// calls the model. A model turn streams the model's pieces and records the full answer
// when the stream ends, under answer()'s rules. The stream stops, closes the model's
// stream and stores nothing when the caller talks over it (cancel()) or a newer turn is
// decided; an error or a consumer that stops early stores nothing either.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, VoiceResponse } = require("./voice.js");
const crowkis = require("./index.js");

const ANSWER = "Here is the answer.";

class Store {
  constructor() {
    this.shared = new Map();
    this.templates = new Map();
    this.writes = [];
  }

  async cgetHit(query, options = {}) {
    const found = (options.template ? this.templates : this.shared).get(query);
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    this.writes.push([query, response, Boolean(options.template)]);
    (options.template ? this.templates : this.shared).set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const sessionOn = (store, options = {}) =>
  new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...options });

const fields = (d) => [d.stored, d.notStored, d.empty, d.reason, d.cacheable, d.messages, d.turn];

async function* words(text) {
  if (text === null || text === undefined) return;
  if (!text) {
    yield text;
    return;
  }
  const parts = text.split(" ");
  for (let i = 0; i < parts.length; i += 1) yield parts[i] + (i < parts.length - 1 ? " " : "");
}

async function readAll(stream) {
  const out = [];
  for await (const piece of stream) out.push(piece);
  return out;
}

// A model stream that records whether it was read to the end or closed.
function upstream(pieces, { failAt = null } = {}) {
  const state = { read: 0, closed: false };
  state.iterator = {
    [Symbol.asyncIterator]() {
      return this;
    },
    async next() {
      if (failAt !== null && state.read === failAt) throw new Error("model stream broke");
      if (state.read >= pieces.length) return { done: true, value: undefined };
      state.read += 1;
      return { done: false, value: pieces[state.read - 1] };
    },
    async return() {
      state.closed = true;
      return { done: true, value: undefined };
    },
  };
  return state;
}

const CALLS = [
  [["what is your refund policy"], [ANSWER], {}],
  [["my order 48213 has not arrived where is it"], [ANSWER], {}],
  [["what is your refund policy", "and how long does that take"], [ANSWER, ANSWER], {}],
  [["I am Priya Sharma", "what plan am I on"], [ANSWER, ANSWER], {}],
  [["what is your refund policy"], [""], {}],
  [["how do I reset my password"], ["Your code is 4471, use it on the reset page."], { values: { code: "4471" } }],
  [["and what about that"], [ANSWER], {}],
  [["refund kitne din mein milta hai"], [ANSWER], {}],
];

test("exported from the package and the voice module", () => {
  assert.strictEqual(typeof VoiceResponse, "function");
  assert.strictEqual(crowkis.VoiceResponse, VoiceResponse);
});

test("streaming ends exactly as answer() does", async () => {
  for (const [turns, replies, options] of CALLS) {
    const aStore = new Store();
    const rStore = new Store();
    const a = sessionOn(aStore, options);
    const r = sessionOn(rStore, options);
    for (let i = 0; i < turns.length; i += 1) {
      const ad = await a.answer(turns[i], async () => replies[i]);
      const stream = await r.respond(turns[i], () => words(replies[i]));
      const spoken = (await readAll(stream)).join("");
      if (stream.decision.needsModel) assert.strictEqual(spoken, replies[i]);
      assert.deepStrictEqual(fields(stream.decision), fields(ad), JSON.stringify(turns));
      assert.strictEqual(stream.decision.text || "", ad.text || "");
    }
    assert.deepStrictEqual(rStore.writes, aStore.writes, JSON.stringify(turns));
    assert.deepStrictEqual(r.transcript, a.transcript);
    assert.deepStrictEqual(r.stats(), a.stats());
  }
});

test("pieces come through as the model writes them; the decision is ready first", async () => {
  let called = 0;
  const session = sessionOn(new Store());
  const stream = await session.respond("what is your refund policy", async function* () {
    called += 1;
    yield "Refunds ";
    yield "take ";
    yield "five days.";
  });
  assert.ok(stream instanceof VoiceResponse);
  assert.strictEqual(stream.decision.needsModel, true);
  assert.strictEqual(called, 0);
  assert.deepStrictEqual(await readAll(stream), ["Refunds ", "take ", "five days."]);
  assert.strictEqual(stream.decision.stored, true);
  assert.strictEqual(stream.decision.text, "Refunds take five days.");
});

test("a cache hit yields the cached answer (and its audio) and never calls the model", async () => {
  const store = new Store();
  store.shared.set("what is your refund policy", ANSWER);
  const session = sessionOn(store, { synthesise: async (text) => Buffer.from(`pcm:${text}`) });
  const stream = await session.respond("what is your refund policy", () => {
    throw new Error("model called");
  });
  assert.strictEqual(stream.decision.servedFromCache, true);
  assert.strictEqual(String(stream.decision.audio), `pcm:${ANSWER}`);
  assert.deepStrictEqual(await readAll(stream), [ANSWER]);
});

test("a filler yields its reply", async () => {
  const stream = await sessionOn(new Store(), { fillers: { hello: "Hi, how can I help?" } }).respond("hello", () => {
    throw new Error("model called");
  });
  assert.deepStrictEqual(await readAll(stream), ["Hi, how can I help?"]);
});

test("the model may return a string, a promise of one, or a plain iterable", async () => {
  for (const llm of [() => ANSWER, async () => ANSWER, () => ["Here is ", "the answer."]]) {
    const session = sessionOn(new Store());
    const stream = await session.respond("what is your refund policy", llm);
    assert.strictEqual((await readAll(stream)).join(""), ANSWER);
    assert.strictEqual(stream.decision.stored, true);
  }
});

test("the model reads the system prompt, then the chosen messages or the whole call", async () => {
  const seen = [];
  const session = sessionOn(new Store());
  await readAll(await session.respond("what is your refund policy", (m) => seen.push(m) && [ANSWER], { system: "Be brief." }));
  assert.deepStrictEqual(seen[0], [
    { role: "system", content: "Be brief." },
    { role: "user", content: "what is your refund policy" },
  ]);
  await readAll(await session.respond("my order 48213 has not arrived where is it", (m) => seen.push(m) && [ANSWER]));
  assert.strictEqual(seen[1].length, 3);
  assert.deepStrictEqual(seen[1].at(-1), { role: "user", content: "my order 48213 has not arrived where is it" });
});

test("null pieces are skipped and other types refused", async () => {
  const session = sessionOn(new Store());
  assert.deepStrictEqual(await readAll(await session.respond("what is your refund policy", () => ["A", null, "B"])), ["A", "B"]);
  await assert.rejects(readAll(await session.respond("how do I reset my password", () => [{ choices: [] }])), /text/);
});

test("private, an empty stream, and read-once", async () => {
  const store = new Store();
  const session = sessionOn(store);
  let stream = await session.respond("what is your refund policy", () => [ANSWER], { private: true });
  await readAll(stream);
  assert.strictEqual(stream.decision.stored, false);
  assert.deepStrictEqual(store.writes, []);
  stream = await session.respond("how do I reset my password", () => []);
  assert.deepStrictEqual(await readAll(stream), []);
  assert.strictEqual(stream.decision.empty, true);
  assert.throws(() => stream[Symbol.asyncIterator](), /once/);
});

test("a barge-in stops the stream, closes the model's stream and stores nothing", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const model = upstream(["Refunds ", "take ", "five ", "days."]);
  const stream = await session.respond("what is your refund policy", () => model.iterator);
  const spoken = [];
  for await (const piece of stream) {
    spoken.push(piece);
    if (spoken.length === 2) session.cancel();
  }
  assert.deepStrictEqual(spoken, ["Refunds ", "take "]);
  assert.strictEqual(model.closed, true);
  assert.ok(model.read < 4);
  assert.strictEqual(stream.decision.stored, false);
  assert.match(stream.decision.notStored, /moved on/);
  assert.deepStrictEqual(store.writes, []);
  assert.deepStrictEqual(session.transcript, []);
});

test("a newer turn stops the older stream", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const model = upstream(["Refunds ", "take ", "five ", "days."]);
  const stream = await session.respond("what is your refund policy", () => model.iterator);
  const it = stream[Symbol.asyncIterator]();
  assert.strictEqual((await it.next()).value, "Refunds ");
  await session.decide("how do I reset my password");
  assert.strictEqual((await it.next()).done, true);
  assert.strictEqual(model.closed, true);
  assert.strictEqual(stream.decision.stored, false);
  assert.deepStrictEqual(store.writes, []);
});

test("a model error rejects, stores nothing, and the turn can still be recorded", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const model = upstream(["Refunds ", "take "], { failAt: 1 });
  const stream = await session.respond("what is your refund policy", () => model.iterator);
  await assert.rejects(readAll(stream), /broke/);
  assert.strictEqual(model.closed, true);
  assert.deepStrictEqual(store.writes, []);
  await session.record(stream.decision, "Sorry, let me check that for you.");
  assert.strictEqual(stream.decision.stored, true);
});

test("a consumer that stops early stores nothing", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const model = upstream(["Refunds ", "take ", "five ", "days."]);
  const stream = await session.respond("what is your refund policy", () => model.iterator);
  for await (const piece of stream) {
    assert.ok(piece);
    break;
  }
  assert.strictEqual(model.closed, true);
  assert.deepStrictEqual(store.writes, []);
  assert.strictEqual(stream.decision.stored, false);
});

test("talked over before the first read: the model is never called, and it is not empty", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const stream = await session.respond("what is your refund policy", () => {
    throw new Error("model called");
  });
  session.cancel();
  assert.deepStrictEqual(await readAll(stream), []);
  assert.strictEqual(stream.decision.empty, false);
  assert.match(stream.decision.notStored, /moved on/);
  assert.deepStrictEqual(store.writes, []);
});

test("works when decide() is overridden", async () => {
  const { TurnDecision } = require("./voice.js");
  class Custom extends VoiceSession {
    async decide(said) {
      const original = await super.decide(said);
      const copy = new TurnDecision(original.action, { text: original.text, reason: original.reason });
      Object.assign(copy, { messages: original.messages, cacheable: original.cacheable, turn: original.turn });
      copy._session = original._session;
      return copy;
    }
  }
  const store = new Store();
  const seen = [];
  const session = new Custom(new Agent("caller", { client: store }), { voice: "v" });
  await readAll(await session.respond("my order 48213 has not arrived where is it", (m) => seen.push(m) && [ANSWER]));
  assert.deepStrictEqual(seen[0].at(-1), { role: "user", content: "my order 48213 has not arrived where is it" });
  assert.deepStrictEqual(session.transcript[0], { role: "user", content: "my order 48213 has not arrived where is it" });
});

test("a model stream whose return() fails still stops cleanly", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const model = upstream(["Refunds ", "take ", "days."]);
  model.iterator.return = async () => {
    throw new Error("socket already gone");
  };
  const stream = await session.respond("what is your refund policy", () => model.iterator);
  for await (const piece of stream) {
    assert.ok(piece);
    break;
  }
  assert.deepStrictEqual(store.writes, []);
});

test("recording mid-stream stops the stream", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const stream = await session.respond("what is your refund policy", () => ["Refunds ", "take ", "days."]);
  const it = stream[Symbol.asyncIterator]();
  await it.next();
  await session.record(stream.decision, "Refunds take five business days.");
  assert.strictEqual((await it.next()).done, true);
  assert.deepStrictEqual(store.writes, [["what is your refund policy", "Refunds take five business days.", false]]);
});

test("close() while a piece is pending stores nothing", async () => {
  const store = new Store();
  const session = sessionOn(store);
  let release;
  const pending = new Promise((r) => (release = r));
  const model = {
    [Symbol.asyncIterator]() {
      return this;
    },
    async next() {
      await pending;
      return { done: true, value: undefined };
    },
  };
  const stream = await session.respond("what is your refund policy", () => model);
  const it = stream[Symbol.asyncIterator]();
  const next = it.next();
  const closing = stream.close();
  release();
  await Promise.allSettled([next, closing]);
  assert.deepStrictEqual(store.writes, []);
  assert.strictEqual(stream.decision.stored, false);
});

test("close() before reading: the model is never called, and a second read fails", async () => {
  const session = sessionOn(new Store());
  const stream = await session.respond("what is your refund policy", () => {
    throw new Error("model called");
  });
  await stream.close();
  assert.throws(() => stream[Symbol.asyncIterator](), /once/);
});

test("a model that throws at once, or rejects, stores nothing", async () => {
  for (const llm of [
    () => {
      throw new Error("boom");
    },
    async () => {
      throw new Error("boom");
    },
  ]) {
    const store = new Store();
    const stream = await sessionOn(store).respond("what is your refund policy", llm);
    await assert.rejects(readAll(stream), /boom/);
    assert.deepStrictEqual(store.writes, []);
  }
});

test("empty pieces, Unicode, a String object and a long stream", async () => {
  const pieces = ["", "\u0930\u093f\u092b\u0902\u0921 ", "\u{1F44D} ", "", "five days."];
  let stream = await sessionOn(new Store()).respond("what is your refund policy", () => pieces);
  assert.deepStrictEqual(await readAll(stream), pieces.filter(Boolean));
  assert.strictEqual(stream.decision.text, pieces.join(""));
  stream = await sessionOn(new Store()).respond("what is your refund policy", () => new String(ANSWER));
  assert.deepStrictEqual(await readAll(stream), [ANSWER]);
  stream = await sessionOn(new Store()).respond("how do I reset my password", () => Array(10000).fill("word "));
  assert.strictEqual((await readAll(stream)).length, 10000);
  assert.strictEqual(stream.decision.stored, true);
});
