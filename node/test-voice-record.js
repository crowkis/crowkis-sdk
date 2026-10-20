"use strict";
// VoiceSession.record(): save the answer from your own model call (same as Python's
// python/tests/test_voice_record.py). decide(), then your model, then
// record(decision, text) must do exactly what answer() does. It only takes a decision
// this session made for a model turn, once. answer() itself is unchanged.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, TurnDecision } = require("./voice.js");

const ANSWER = "Here is the answer.";

// The server: a shared store and a template store, matched on the exact key
// (as in test-voice-stress-bugs.js).
class Store {
  constructor(refuse = null) {
    this.shared = new Map();
    this.templates = new Map();
    this.writes = [];
    this.refuse = refuse;
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
    if (this.refuse) throw this.refuse;
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

const fields = (d) => [d.action, d.text, d.stored, d.notStored, d.empty, d.reason, d.cacheable, d.messages, d.turn];

// Calls that exercise every rule: [turns, what the model says to each, session options].
const CALLS = [
  [["what is your refund policy"], [ANSWER], {}],
  [["my order 48213 has not arrived where is it"], [ANSWER], {}],
  [["what is your refund policy", "and how long does that take"], [ANSWER, ANSWER], {}],
  [["I am Priya Sharma", "what plan am I on"], [ANSWER, ANSWER], {}],
  [["what is your refund policy"], [""], {}],
  [["what is your refund policy"], [null], {}],
  [["how do I reset my password"], ["Your code is 4471, use it on the reset page."], { values: { code: "4471" } }],
  [["and what about that"], [ANSWER], {}],
  [["refund kitne din mein milta hai"], [ANSWER], {}],
  [["\u092e\u0947\u0930\u093e \u0930\u093f\u092b\u0902\u0921 \u0915\u092c \u0906\u090f\u0917\u093e"], [ANSWER], {}],
];

async function run(turns, replies, options, { useRecord, refuse = null }) {
  const store = new Store(refuse);
  const session = sessionOn(store, options);
  const decisions = [];
  for (let i = 0; i < turns.length; i += 1) {
    let decision;
    if (useRecord) {
      decision = await session.decide(turns[i]);
      if (decision.needsModel) decision = await session.record(decision, replies[i]);
    } else {
      decision = await session.answer(turns[i], async () => replies[i]);
    }
    decisions.push(decision);
  }
  return { store, session, decisions };
}

test("record() does exactly what answer() does", async () => {
  for (const [turns, replies, options] of CALLS) {
    const a = await run(turns, replies, options, { useRecord: false });
    const r = await run(turns, replies, options, { useRecord: true });
    const label = JSON.stringify(turns);
    assert.deepStrictEqual(r.store.writes, a.store.writes, label);
    assert.deepStrictEqual(r.session.transcript, a.session.transcript, label);
    assert.deepStrictEqual(r.session.stats(), a.session.stats(), label);
    assert.deepStrictEqual(r.decisions.map(fields), a.decisions.map(fields), label);
  }
});

test("a refused write is reported the same and never rejects", async () => {
  const refuse = new Error("ERR tenant cap reached");
  const a = await run(["what is your refund policy"], [ANSWER], {}, { useRecord: false, refuse });
  const r = await run(["what is your refund policy"], [ANSWER], {}, { useRecord: true, refuse });
  assert.deepStrictEqual(fields(r.decisions[0]), fields(a.decisions[0]));
  assert.strictEqual(r.decisions[0].stored, false);
  assert.match(r.decisions[0].notStored, /tenant cap/);
});

test("record() resolves to the same decision, filled in", async () => {
  const session = sessionOn(new Store());
  const decision = await session.decide("what is your refund policy");
  assert.strictEqual(await session.record(decision, ANSWER), decision);
  assert.deepStrictEqual([decision.text, decision.stored, decision.notStored], [ANSWER, true, ""]);
});

test("a decision keeps its session out of logs and JSON", async () => {
  const session = sessionOn(new Store());
  const decision = await session.decide("what is your refund policy");
  assert.ok(!Object.keys(decision).some((k) => k.startsWith("_")));
  assert.doesNotThrow(() => JSON.stringify(decision));
});

test("a turn served from the cache or a filler cannot be recorded", async () => {
  const store = new Store();
  store.shared.set("what is your refund policy", ANSWER);
  const session = sessionOn(store, { fillers: { hello: "Hi, how can I help?" } });
  const served = await session.decide("what is your refund policy");
  assert.strictEqual(served.action, "serve");
  await assert.rejects(session.record(served, "something else"), /model/);
  const filler = await session.decide("hello");
  await assert.rejects(session.record(filler, ANSWER), /filler/);
  assert.deepStrictEqual(store.writes, []);
});

test("a decision from another session, or made by hand, is refused", async () => {
  const store = new Store();
  const one = sessionOn(store);
  const other = sessionOn(store);
  const decision = await one.decide("what is your refund policy");
  await assert.rejects(other.record(decision, ANSWER), /another/);
  await assert.rejects(other.record(new TurnDecision("infer"), ANSWER), /decide/);
  assert.deepStrictEqual(store.writes, []);
  assert.deepStrictEqual(other.transcript, []);
});

test("a turn is recorded once, and an answer() turn cannot be recorded again", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, ANSWER);
  await assert.rejects(session.record(decision, "a second answer"), /already/);
  assert.strictEqual(store.writes.length, 1);
  assert.strictEqual(session.transcript.length, 2);
  const answered = await session.answer("how do I reset my password", async () => ANSWER);
  await assert.rejects(session.record(answered, ANSWER), /already/);
});

test("after a barge-in, or for an older turn, nothing is stored", async () => {
  let store = new Store();
  let session = sessionOn(store);
  let decision = await session.decide("what is your refund policy");
  session.cancel();
  await session.record(decision, ANSWER);
  assert.strictEqual(decision.stored, false);
  assert.match(decision.notStored, /moved on/);
  assert.deepStrictEqual(store.writes, []);
  assert.deepStrictEqual(session.transcript, []);

  store = new Store();
  session = sessionOn(store);
  decision = await session.decide("what is your refund policy");
  await session.decide("how do I reset my password");
  await session.record(decision, ANSWER);
  assert.strictEqual(decision.stored, false);
  assert.match(decision.notStored, /moved on/);
  assert.deepStrictEqual(store.writes, []);
});

test("private keeps a shareable answer to this call", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const decision = await session.decide("what is your refund policy");
  assert.strictEqual(decision.cacheable, true);
  await session.record(decision, "Your refund of 40 dollars was approved today.", { private: true });
  assert.strictEqual(decision.stored, false);
  assert.match(decision.notStored, /tool/);
  assert.deepStrictEqual(store.writes, []);
  assert.strictEqual(session.transcript.at(-1).content, "Your refund of 40 dollars was approved today.");
});

test("answer() still calls the model with the chosen messages, and never on a hit", async () => {
  const seen = [];
  const session = sessionOn(new Store());
  const decision = await session.answer("what is your refund policy", async (m) => seen.push(m) && ANSWER, {
    system: "Be brief.",
  });
  assert.deepStrictEqual(seen, [
    [{ role: "system", content: "Be brief." }, { role: "user", content: "what is your refund policy" }],
  ]);
  assert.strictEqual(decision.stored, true);
  const store = new Store();
  store.shared.set("what is your refund policy", ANSWER);
  const served = await sessionOn(store).answer("what is your refund policy", async () => {
    throw new Error("the model was called");
  });
  assert.deepStrictEqual([served.action, served.text], ["serve", ANSWER]);
});

// A store whose lookups for `slow` questions finish later than the others.
class SlowStore extends Store {
  constructor(slow) {
    super();
    this.slow = slow;
  }

  async cgetHit(query, options = {}) {
    if (this.slow.some((q) => query.includes(q))) await new Promise((r) => setTimeout(r, 60));
    return super.cgetHit(query, options);
  }
}

// Two decide() calls in flight at once, the older one finishing last: the newer
// turn's answer must still be judged by the newer turn's own rules. A private
// answer was put in the shared cache here before the fix.
for (const said of ["Twelve years old.", "The blue one, size nine please.", "and how long does that take"]) {
  test(`overlapping decide(): an older turn finishing last never makes "${said}" shareable`, async () => {
    const store = new SlowStore(["refund policy for orders"]);
    const session = sessionOn(store);
    const [older, newer] = await Promise.all([
      session.decide("what is your refund policy for orders"),
      session.decide(said),
    ]);
    assert.ok(older.turn < newer.turn);
    assert.strictEqual(newer.cacheable, false);
    await session.record(newer, "Thanks Asha Rao, account 99812 is now updated.");
    assert.strictEqual(newer.stored, false);
    assert.deepStrictEqual(store.writes, []);
  });
}

test("overlapping answer() calls never share the newer turn's private answer", async () => {
  const store = new SlowStore(["refund policy for orders"]);
  const session = sessionOn(store);
  await Promise.all([
    session.answer("what is your refund policy for orders", async () => ANSWER),
    session.answer("Twelve years old.", async () => {
      await new Promise((r) => setTimeout(r, 150)); // still answering when the older lookup lands
      return "Thanks Asha Rao, account 99812 is now updated.";
    }),
  ]);
  assert.ok(!store.writes.some(([, answer]) => answer.includes("99812")), JSON.stringify(store.writes));
});

test("answer() works when decide() is overridden", async () => {
  class Custom extends VoiceSession {
    async decide(said) {
      const original = await super.decide(said);
      const copy = new TurnDecision(original.action, { text: original.text, confidence: original.confidence, reason: original.reason });
      Object.assign(copy, { messages: original.messages, cacheable: original.cacheable, turn: original.turn });
      return copy;
    }
  }
  const store = new Store();
  const session = new Custom(new Agent("caller", { client: store }), { voice: "v" });
  const decision = await session.answer("what is your refund policy", async () => ANSWER);
  assert.strictEqual(decision.text, ANSWER);
  assert.deepStrictEqual(store.writes, [["what is your refund policy", ANSWER, false]]);
});

test("a model that throws records nothing", async () => {
  const store = new Store();
  const session = sessionOn(store);
  await assert.rejects(session.answer("what is your refund policy", async () => {
    throw new Error("model down");
  }), /model down/);
  assert.deepStrictEqual(store.writes, []);
  assert.deepStrictEqual(session.transcript, []);
});

test("private with a personal turn and with an empty answer", async () => {
  const store = new Store();
  const session = sessionOn(store);
  let decision = await session.decide("my order 48213 has not arrived where is it");
  await session.record(decision, "Order 48213 left the depot.", { private: true });
  assert.strictEqual(decision.stored, false);
  decision = await session.decide("what is your refund policy");
  await session.record(decision, "", { private: true });
  assert.strictEqual(decision.empty, true);
  assert.deepStrictEqual(store.writes, []);
});

test("something that is not a decision is refused", async () => {
  const session = sessionOn(new Store());
  for (const wrong of [null, undefined, { action: "infer" }, "infer"]) {
    await assert.rejects(session.record(wrong, ANSWER), /TurnDecision/);
  }
});

test("two records of one decision at once write it once", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const decision = await session.decide("what is your refund policy");
  const results = await Promise.allSettled([session.record(decision, ANSWER), session.record(decision, ANSWER)]);
  assert.deepStrictEqual(results.map((r) => r.status).sort(), ["fulfilled", "rejected"]);
  assert.strictEqual(store.writes.length, 1);
  assert.strictEqual(session.transcript.length, 2);
});

test("a kept decision drops the caller's words, and a served one never has them", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const decision = await session.decide("what is your refund policy");
  await session.record(decision, ANSWER);
  assert.strictEqual(decision._said, null);
  assert.ok(decision._session instanceof WeakRef);
  const served = await session.decide("what is your refund policy");
  assert.strictEqual(served.action, "serve");
  assert.strictEqual(served._said, null);
});
