"use strict";

// The security audit of release/0.5.2 (14 Oct 2026): the same cases as
// python/tests/test_voice_security_audit.py (its Pipecat case is Python only).

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession } = require("./voice.js");

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
    this.writes.push({ query, response, template: Boolean(options.template) });
    (options.template ? this.templates : this.shared).set(query, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const session = (client, options = {}) => new VoiceSession(new Agent("support", { client }), { voice: "v", ...options });

const ROOTS = [
  "Priya Sharma.", "Sharma, Priya.", "Anjali Verma.", "Delhi.", "Lupus.", "Gold member.", "Sixty five.",
  "Muslim.", "Bipolar.", "Schizophrenia.", "Twelve years old.", "Fourteen.", "Kosher.", "Halal food.",
];

test("a template never carries details the caller did not declare", async () => {
  let server = new Store();
  const a = session(server, { values: { order_id: "ORD-111" }, shareTemplates: true });
  await a.answer("hello, my name is Priya Sharma", () => "Hi Priya, how can I help?");
  await a.answer(
    "when will my order arrive",
    () => "Priya, your order ORD-111 is going to 42 Park Lane, and your balance is fifteen hundred rupees."
  );
  assert.deepStrictEqual(server.writes.filter((w) => w.template), []);
  const heard = await session(server, { values: { order_id: "ORD-222" } }).decide("when will my order arrive");
  assert.notStrictEqual(heard.action, "serve");
  for (const answer of [
    "Your order ORD-111 arrives at 42 Park Lane.",
    "Your order ORD-111 arrives Tuesday; your balance is fifteen hundred rupees.",
    "Your order ORD-111 arrives Tuesday, we will email priya at gmail dot com.",
    "Your order ORD-111 arrives Tuesday, and the doctor says your pregnancy is fine.",
    "Priya, your order ORD-111 arrives Tuesday.",
  ]) {
    server = new Store();
    const s = session(server, { values: { order_id: "ORD-111" }, shareTemplates: true });
    await s.answer("hello, my name is Priya Sharma", () => "Hi, how can I help?");
    await s.answer("when will my order arrive", () => answer);
    assert.deepStrictEqual(server.writes.filter((w) => w.template), [], answer);
  }
  server = new Store();
  await session(server, { values: { order_id: "ORD-111" }, shareTemplates: true }).answer(
    "when will my order arrive", () => "Your order ORD-111 arrives on Tuesday."
  );
  assert.deepStrictEqual(server.writes.filter((w) => w.template).map((w) => w.response), ["Your order {order_id} arrives on Tuesday."]);
});

test("a cut-off personal question never becomes a template", async () => {
  for (const said of ["when will i get my order on the", "will my order arrive by", "when will my order arrive by um"]) {
    const server = new Store();
    await session(server, { values: { order_id: "ORD-111" }, shareTemplates: true })
      .answer(said, () => "Your order ORD-111 is due to arrive on Tuesday.");
    assert.deepStrictEqual(server.writes.filter((w) => w.template), [], said);
  }
  // A finished one still is.
  const server = new Store();
  await session(server, { values: { order_id: "ORD-111" }, shareTemplates: true })
    .answer("will my order arrive by Friday", () => "Your order ORD-111 arrives on Tuesday.");
  assert.strictEqual(server.writes.filter((w) => w.template).length, 1);
});

test("a short or unasked reply never roots a shared chain or is stored alone", async () => {
  for (const root of ROOTS) {
    const server = new Store();
    const s = session(server);
    await s.answer(root, () => "Okay.");
    await s.answer("and what is the refund policy?", () => "Refunds take 5 days.");
    assert.deepStrictEqual(server.writes, [], root);
  }
  const server = new Store();
  const s = session(server);
  await s.answer("What is the refund policy?", () => "Refunds take 5 days.");
  await s.answer("and for sale items?", () => "The same.");
  assert.deepStrictEqual(server.writes.map((w) => w.query), [
    "What is the refund policy?", "What is the refund policy? || and for sale items?",
  ]);
});

test("a served answer filled with this caller's values is not shareable audio", async () => {
  const server = new Store();
  server.templates.set("when will my order arrive", "Your order {order_id} ships Tuesday.");
  const filled = await session(server, { values: { order_id: "ORD-111" } }).decide("when will my order arrive");
  assert.strictEqual(filled.action, "serve");
  assert.strictEqual(filled.audioShareable, false);
  server.shared.set("what are your opening hours", "Nine to five.");
  const plain = await session(server).decide("what are your opening hours");
  assert.strictEqual(plain.audioShareable, true);
  assert.throws(() => { plain.audioShareable = false; }, TypeError); // read-only
});

test("a detail said before a question keeps the turn private", async () => {
  for (const root of [
    "Gay, is that okay?", "Muslim, is the food halal?", "Bipolar, can you help?",
    "Twelve years old, can I sign up?", "Priya Sharma, can you help?", "Lupus, what do you cover?",
    "Fourteen, can I open an account?", "Gay couple, can we book a room?", "Jewish, do you serve kosher?",
    "Priya Sharma calling, is the store open?",
  ]) {
    const server = new Store();
    const s = session(server);
    await s.answer(root, () => "Okay.");
    await s.answer("and what is the refund policy?", () => "Refunds take 5 days.");
    assert.deepStrictEqual(server.writes, [], root);
  }
  // A greeting or an acknowledgement first is neither: still shared.
  for (const said of ["Hi, what are your hours?", "Okay, how do I reset my password?", "Thanks - what is the refund policy?"]) {
    const server = new Store();
    await session(server).answer(said, () => "Here you go.");
    assert.deepStrictEqual(server.writes.map((w) => w.query), [said], said);
  }
});

test("templates are off by default", async () => {
  const question = "when will my order arrive";
  for (const [earlier, asked, answer] of [
    [["Priya."], question, "Priya, your order ORD-111 arrives Tuesday."],
    [["my name is priya sharma"], question, "Priya, your order ORD-111 arrives Tuesday."],
    [["i live in pune"], question, "Your order ORD-111 ships to Pune on Tuesday."],
    [["my wife anjali will collect it"], question, "Anjali can collect order ORD-111 on Tuesday."],
    [["me llamo josé"], question, "José, tu pedido ORD-111 llega el martes."],
    [["मेरा नाम प्रिया है"], "मेरा ऑर्डर कब आएगा", "प्रिया जी, आपका ऑर्डर ORD-111 मंगलवार को आएगा।"],
    [[], question, "Your order ORD-111 arrives on the third of March, Mrs Mehta."],
    [[], question, "Your order ORD-111 has nine items and arrives Tuesday."],
    [["i live on baker street"], question, "Your order ORD-111 goes to Baker Street on Tuesday."],
    [[], question, "Your order ORD-111 arrives in three to five days."],
  ]) {
    const server = new Store();
    const s = session(server, { values: { order_id: "ORD-111" } });
    for (const turn of earlier) await s.answer(turn, () => "Okay.");
    await s.decide(asked);
    assert.strictEqual(await s._recordModelTurn(asked, answer), "private", answer);
    assert.deepStrictEqual(server.writes.filter((w) => w.template), [], answer);
  }
  // On, the old behaviour holds.
  const server = new Store();
  const s = session(server, { values: { order_id: "ORD-111" }, shareTemplates: true });
  await s.decide(question);
  assert.strictEqual(await s._recordModelTurn(question, "Your order ORD-111 arrives in three to five days."), "template");
});
