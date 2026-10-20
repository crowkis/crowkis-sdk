"use strict";

// Caller turns the session never decided: a private turn kept with recordPrivateTurn
// (a LiveKit turn with RAG or CRM data, a realtime model), or history the app gave the
// model before the call reached Crowkis. One that tells the call something a later answer
// may depend on keeps the rest of the call off the shared cache, as a decided one does.
// Mirrors python/tests/test_voice_undecided_turns.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession } = require("./voice.js");

class FakeClient {
  constructor(shared = {}) {
    this.shared = new Map(Object.entries(shared));
    this.reads = [];
    this.writes = [];
  }

  async cgetHit(query, options = {}) {
    this.reads.push(query);
    const response = options.template ? undefined : this.shared.get(query);
    if (response === undefined) return null;
    const body = Buffer.from(String(response));
    return { response: body, text: body.toString(), similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }

  async cset(query, response, options = {}) {
    this.writes.push({ query, response, template: Boolean(options.template) });
    if (!options.template) this.shared.set(query, response);
  }

  async ctoolget() { return null; }
  async ctoolset() {}
  async close() {}
}

// What the caller told the call, then a question whose shared answer ignores it.
const CASES = {
  trip: ["I'm planning a trip to Goa in December.", "What should I pack?"],
  language: ["Reply only in Hindi from now on.", "What is the capital of Japan?"],
  child_age: ["I have a 3 year old daughter.", "What vaccines are due at this age?"],
};

const session = (client) => new VoiceSession(new Agent("caller", { client }), { voice: "v" });

async function ask(talk, question) {
  const seen = [];
  const decision = await talk.answer(question, async (messages) => { seen.push(messages); return "Here is the answer."; });
  return { decision, seen };
}

async function assertPrivate(told, later, tell) {
  const client = new FakeClient({ [later]: "Another caller's plain answer." });
  const talk = session(client);
  tell(talk, told);
  const { decision, seen } = await ask(talk, later);
  assert.strictEqual(decision.action, "infer", later);
  assert.strictEqual(decision.messages, null, "the model must read the whole call");
  assert.strictEqual(decision.cacheable, false);
  assert.deepStrictEqual(client.reads, [], "nothing is looked up");
  assert.deepStrictEqual(client.writes, [], "nothing is written");
  assert.ok(seen.at(-1).some((m) => m.content === told), "what was told reaches the model");
}

test("a private turn that tells the call something keeps the rest off the shared cache", async () => {
  for (const [told, later] of Object.values(CASES)) {
    await assertPrivate(told, later, (talk, said) => talk.recordPrivateTurn(said, "Noted."));
  }
});

test("history the session never decided keeps the rest off the shared cache", async () => {
  for (const [told, later] of Object.values(CASES)) {
    await assertPrivate(told, later, (talk, said) => {
      talk.transcript.push({ role: "user", content: said }); // the app's own history
      talk._heard(said);
    });
  }
});

test("plain turns keep the shared cache", async () => {
  // Must still work: small talk, a question, a name or a number tell the call nothing.
  for (const said of ["what is your refund policy", "Hi, I have a question.", "I am Priya, account 4471.", "Gracias, ¿me ayudas?"]) {
    const client = new FakeClient({ "What should I pack?": "Light clothes." });
    const talk = session(client);
    talk.recordPrivateTurn(said, "Sure.");
    talk._heard(said);
    const { decision } = await ask(talk, "What should I pack?");
    assert.strictEqual(decision.action, "serve", said);
    assert.notDeepStrictEqual(client.reads, []);
  }
});

test("a turn never decided is judged as a decided one", async () => {
  for (const said of ["I'm allergic to peanuts.", "My son is 12 years old.", "Mumbai to Bangalore on the 14th.",
    "मेरा सवाल है", "mujhe Hindi mein jawab do", "I have 2 orders", "I'm frustrated", "check my order",
    "Gold member here, my plan renews in May", "x".repeat(5000)]) {
    const decided = session(new FakeClient());
    await decided.decide(said);
    const heard = session(new FakeClient());
    heard._heard(said);
    assert.strictEqual(heard._tainted, decided._tainted, said.slice(0, 40));
  }
});

test("empty or missing text changes nothing", async () => {
  const talk = session(new FakeClient({ "What should I pack?": "Light clothes." }));
  for (const said of ["", "   ", null, undefined]) talk._heard(said);
  assert.strictEqual((await ask(talk, "What should I pack?")).decision.action, "serve");
});

test("a cancelled turn still keeps what the caller said", () => {
  // The caller said it, whatever happened to the answer: over-privacy only costs savings.
  const talk = session(new FakeClient());
  talk.cancel();
  talk._heard("Reply only in Hindi from now on.");
  assert.strictEqual(talk._tainted, true);
});
