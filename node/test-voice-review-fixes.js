"use strict";

// One test per finding of the independent review of the voice bug-fix (14 Oct
// 2026), the same cases as python/tests/test_voice_review_fixes.py. Each runs the
// reviewer's own turns through VoiceSession.answer, with a fake client standing in
// for the server, next to "must still work" controls for the opposite case.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, _isPersonal } = require("./voice.js");

const ANSWER = "Here is the answer.";

class Store {
  constructor() {
    this.shared = new Map();
    this.reads = [];
    this.writes = [];
  }

  async cgetHit(query, options = {}) {
    this.reads.push(query);
    const found = options.template ? undefined : this.shared.get(query);
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    this.writes.push([query, response, Boolean(options.template)]);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

const sessionOn = (store) => new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });
const user = (content) => ({ role: "user", content });
const last = (list) => list[list.length - 1];

// The model says `reply` to the last turn and ANSWER to the ones before it.
async function call(turns, { reply = ANSWER, store = new Store() } = {}) {
  const session = sessionOn(store);
  const seen = [];
  const decisions = [];
  for (let index = 0; index < turns.length; index += 1) {
    const said = index === turns.length - 1 ? reply : ANSWER;
    decisions.push(await session.answer(turns[index], (messages) => {
      seen.push(messages);
      return said;
    }));
  }
  return { store, session, decisions, seen };
}

async function keptPrivate(said, ...before) {
  const { store, decisions } = await call([...before, said]);
  assert.strictEqual(last(decisions).cacheable, false, said);
  assert.ok(store.writes.every(([query]) => !query.includes(said)), said);
}

async function shared(said, ...before) {
  const { store, decisions } = await call([...before, said]);
  assert.strictEqual(last(decisions).cacheable, true, said);
  assert.ok(store.writes.some(([q, a, t]) => q === said && a === ANSWER && !t), said);
  assert.strictEqual(_isPersonal(said), false, said);
}

// The last turn is answered with the whole call in view, and nothing of it is stored.
async function followsThePrivateTurn(turns) {
  const { store, decisions, seen } = await call(turns);
  assert.strictEqual(last(decisions).messages, null, turns.join(" >> "));
  assert.strictEqual(last(decisions).cacheable, false, turns.join(" >> "));
  assert.deepStrictEqual(last(seen)[0], user(turns[0]));
  assert.deepStrictEqual(last(last(seen)), user(last(turns)));
  assert.ok(store.writes.every(([query]) => !query.includes(last(turns))));
}

test("review 01: a first-person disclosure keeps a how-to private", async () => {
  for (const said of [
    "I'm pregnant, what should I do about the nausea?",
    "My doctor prescribed 50mg of sertraline, what should I do if I miss a dose?",
    "I'm HIV positive, how do I get the medicine?",
    "I'm allergic to penicillin, what should I do if I get a rash?",
    "My lawyer told me to sue, how do I file?",
    "My husband hits me, where can I go?",
    "I have HIV, can I still donate blood?",
    "My son was arrested last night, what do I do?",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  // The same words in a generic framing are still shared.
  for (const said of [
    "How do I find a good lawyer?",
    "What should I do if a doctor is late?",
    "What should I bring to a first consultation with a lawyer?",
    "How can I improve my sleep?",
    "How do I add my wife to my plan?",
  ]) {
    await shared(said);
  }
});

test("review 02: names in any form are private", async () => {
  for (const said of [
    "I am Priya Sharma.",
    "Priya speaking, I need help.",
    "Can Priya Sharma pick up the parcel?",
    "Does Mohit have an appointment tomorrow?",
    "Refund status for Rahul Verma",
    "Is the order for Rahul ready?",
    "When is Dr Mehta's appointment for Anjali?",
    "Mi nombre es Carlos.",
    "Je m'appelle Pierre.",
    "Hola, soy Carlos.",
    "Mein Name ist Hans.",
    "Hi, it's Priya again.",
    // Transcripts may come lowercase.
    "i am priya sharma",
    "this is priya",
    "priya here",
    "hola soy carlos",
    "je m'appelle pierre",
    "mera naam rahul hai",
    "me llamo carlos",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  // Product names, weekdays, months and places said in passing are not names.
  for (const said of [
    "Can I pay with Apple Pay at the counter?",
    "Can I use Google Maps to find the store?",
    "What is included in the Premium plan?",
    "Are you open on Monday?",
    "Is the café open on Sundays?",
    "Do you have a sale in December?",
    "Do you deliver to Mumbai?",
    "How long does it take to deliver to Pune?",
    "Is there a store in London?",
  ]) {
    await shared(said);
  }
});

test("review 03: numbers, dates, emails and addresses are private", async () => {
  for (const said of [
    "Is 4409 the right PIN?",
    "My PIN is 4409, how do I change it?",
    "Is forty four oh nine the right PIN?",
    "Was I born on 12/03/1985?",
    "I was born on March 12 1985, can you check?",
    "Track order seven four two please",
    "Where is order 742?",
    "Is priya sharma at gmail the email on file?",
    "Is john at gmail a valid email?",
    "Its j o h n at yahoo",
    "I live at 42 Park Lane, do you deliver there?",
    "I need an ambulance at 42 Park Lane",
    "Can you send it to 221B Baker Street?",
    "I'm 45, can I take ibuprofen?",
    "I earn fifty thousand a month, how much loan can I get?",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  for (const said of [
    "What happened in 1985?",
    "Is the store open 24 hours?",
    "Do you have a 2 year warranty?",
    "What are the top 10 features?",
    "Is the 1,499 plan good for families?",
    "How much is a 2 kg parcel to Delhi?",
  ]) {
    await shared(said);
  }
});

test("review 04: a short follow-up to an emergency keeps the emergency", async () => {
  for (const turns of [
    ["My father collapsed!", "What happens now?"],
    ["My father collapsed!", "Is he going to be okay?"],
    ["My father collapsed!", "Should I give him water?"],
    ["My child swallowed a battery", "How do I make her vomit?"],
    ["I took 20 pills", "What happens now?"],
    ["She is bleeding a lot", "What do I do?"],
    ["I'm pregnant", "Which painkiller is safe?"],
    ["My father collapsed!", "Is he going to be okay?", "What happens now?"],
  ]) {
    await followsThePrivateTurn(turns);
  }
  // After a generic turn, "should I restart it?" behaves as before: shared, alone.
  const { store, decisions, seen } = await call(["What are your opening hours?", "Should I restart it?"]);
  assert.strictEqual(last(decisions).cacheable, true);
  assert.deepStrictEqual(last(seen), [user("Should I restart it?")]);
  assert.ok(store.writes.some(([q, a, t]) => q === "Should I restart it?" && a === ANSWER && !t));
});

test("review 05: a confirmation or a question about this call is never shared", async () => {
  for (const said of [
    "Sounds good to me.",
    "Let's do that then.",
    "Lock it in.",
    "What did you just say?",
    "Repeat the last answer.",
    "What did we talk about?",
  ]) {
    await keptPrivate(said, "Do you have a table for two at 8 pm?");
    await keptPrivate(said);
  }
  await shared("What did the update change?");
});

test("review 06: possessives in other latin-script languages are private", async () => {
  for (const said of [
    "Où est ma commande numéro 4409?",
    "Où sont mes commandes?",
    "Notre commande est en retard?",
    "¿Dónde está mi pedido?",
    "¿Dónde está nuestro pedido?",
    "Cadê meu pedido?",
    "Onde está minha encomenda?",
    "Wo ist meine Bestellung?",
    "Hamara order kab aayega?",
    "Humara order kab aayega?",
    "Apna order kab aayega?",
    "Mai order kab aayega?",
    "Main order kab aayega?",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  for (const said of ["What is the main difference between the plans?", "¿Cuánto cuesta el plan premium?"]) {
    await shared(said);
  }
});

test("review 07: interleaved turns keep their own shareable flag", async () => {
  // Node runs one turn's bookkeeping without yielding, so there is no race to
  // fix here; this pins the same outcome as the Python race test.
  const lookup = "I received a damaged laptop, how do I return it?";
  const store = new Store();
  const session = sessionOn(store);
  let release;
  const first = session.answer(lookup, () => new Promise((resolve) => {
    release = () => resolve("Returns are free within 30 days.");
  }));
  while (!release) await new Promise((resolve) => setImmediate(resolve));
  await session.decide("What are your opening hours?");
  release();
  await first;
  assert.ok(store.writes.every(([query]) => !query.includes(lookup)), JSON.stringify(store.writes));

  const inOrder = await call(["What are your opening hours?", lookup]);
  assert.deepStrictEqual(inOrder.store.writes, [["What are your opening hours?", ANSWER, false]]);
});

test("review 09: an empty answer keeps the infer action", async () => {
  const { store, session, decisions } = await call(["How long does passport police verification take?"], { reply: "  " });
  const decision = last(decisions);
  assert.strictEqual(decision.action, "infer");
  assert.strictEqual(decision.needsModel, true);
  assert.strictEqual(decision.empty, true);
  assert.strictEqual(decision.stored, false);
  assert.strictEqual(session.stats().emptyAnswers, 1);
  assert.deepStrictEqual(store.writes, []);
  const normal = await call(["How long does passport police verification take?"]);
  assert.strictEqual(last(normal.decisions).empty, false);
  assert.throws(() => { decision.empty = false; }, TypeError); // read-only, like needsModel
});

test("review 10: a story with a personal detail never leaves the sdk", async () => {
  for (const said of [
    "I ordered a laptop for my wife Priya Sharma, how do I return it?",
    "I received a damaged item for Priya, how do I return it?",
    "I paid 4,999 for it, how do I get a refund?",
    "I bought it for my son, how do I return it?",
  ]) {
    const store = new Store();
    store.shared.set(said, "Should never be served.");
    const decision = await sessionOn(store).decide(said);
    assert.strictEqual(decision.action, "infer", said);
    assert.deepStrictEqual(store.reads, [], said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  const said = "I received a damaged laptop, how do I return it?";
  const store = new Store();
  store.shared.set(said, "Damaged items can be returned free within 30 days.");
  assert.strictEqual((await sessionOn(store).decide(said)).action, "serve");
  assert.deepStrictEqual(store.reads, [said]);
});

test("review 11: a very long turn is private and classified in bounded time", async () => {
  const longTurn = "what are your opening hours on a normal weekday ".repeat(2500); // 22,500 words
  // CPU time, not wall time: another busy process on the machine must not fail it.
  const started = process.cpuUsage();
  assert.strictEqual(_isPersonal(longTurn), true);
  const store = new Store();
  const decision = await sessionOn(store).decide(longTurn);
  const used = process.cpuUsage(started);
  assert.ok((used.user + used.system) / 1000 < 500);
  assert.strictEqual(decision.action, "infer");
  assert.strictEqual(decision.cacheable, false);
  assert.deepStrictEqual(store.reads, []);
  await shared("What are your opening hours on a normal weekday?");
});

test("review 13: where is my nearest store stays private and generic questions stay shared", async () => {
  // Location-dependent: the answer depends on where this caller is.
  await keptPrivate("Where is my nearest store?");
  assert.strictEqual(_isPersonal("Where is my nearest store?"), true);
  for (const said of [
    "What are your opening hours?",
    "How do I reset a password?",
    "What is the price of the premium plan?",
    "Do you deliver on Sundays?",
    "How do I reset my password?",
  ]) {
    await shared(said);
  }
});
