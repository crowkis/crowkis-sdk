"use strict";

// One test per finding of the second independent review of the voice fixes (14 Oct
// 2026), the same cases as python/tests/test_voice_rereview_fixes.py (its Pipecat
// tests are Python only: there is no Node Pipecat integration).

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, _isPersonal } = require("./voice.js");

const ANSWER = "Here is the answer.";

class Store {
  constructor() {
    this.reads = [];
    this.writes = [];
  }

  async cgetHit(query) {
    this.reads.push(query);
    return null;
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

async function call(turns) {
  const store = new Store();
  const session = sessionOn(store);
  const seen = [];
  const decisions = [];
  for (const said of turns) {
    decisions.push(await session.answer(said, (messages) => {
      seen.push(messages);
      return ANSWER;
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
}

test("a cut-off question is never served or stored", async () => {
  // The real server served "do you deliver on" the Sundays answer at 0.95 (19 Oct).
  for (const said of ["do you deliver on", "Can I pay with my", "What is the price of the", "Do you have parking for",
    "do you deliver on um", "are you open until", "can I return it within"]) {
    const store = new Store();
    const decision = await sessionOn(store).decide(said);
    assert.strictEqual(decision.action, "infer", said);
    assert.deepStrictEqual(store.reads, [], said);
    await keptPrivate(said);
  }
  await shared("Do you deliver on Sundays?");
  await shared("What happened in 1985?"); // a number ends a finished question
  await shared("How do I log in?"); // the verb takes "in" as its own
  await shared("Do you deliver to Besançon?");
});

test("rr 03: a sensitive state with any first-person word stays private", async () => {
  for (const said of [
    "Im pregnant, can i fly",
    "pregnant at 30 weeks, can i fly",
    "pregnant, can i still fly with you",
    "pregnent, can i fly",
    "im allergic to nuts can i eat the curry",
    "allergic to nuts, can i eat the curry",
    "i want to invest my savings, how do i start",
    "what discount do you have for pensioners like me",
    "being a cancer patient do i pay less",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  for (const said of [
    "Is coffee safe for pregnant women?",
    "What should I do if a doctor is late?",
    "How do I find a good lawyer?",
    "Can I book a tennis court for Sunday?",
  ]) {
    await shared(said);
  }
});

test("rr 04: a short turn after a crisis said in words stays with it", async () => {
  for (const turns of [
    ["i want to die", "what number do i call"],
    ["i feel like ending my life", "is anyone there"],
    ["i want to kill myself", "nobody cares anyway"],
  ]) {
    const { store, decisions, seen } = await call(turns);
    assert.strictEqual(last(decisions).messages, null, turns.join(" >> "));
    assert.strictEqual(last(decisions).cacheable, false, turns.join(" >> "));
    assert.deepStrictEqual(last(seen)[0], user(turns[0]));
    assert.ok(store.writes.every(([q]) => !q.includes(last(turns))));
  }
  await shared("what number do i call", "What are your opening hours?");
});

test("rr 05: names need a person, and places, brands and festivals stay shared", async () => {
  for (const said of [
    "Does Mohit have an appointment tomorrow?",
    "Can Priya Sharma pick up the parcel?",
    "Refund status for Rahul Verma",
    "is sanjay's order ready",
    "Dr. Iyer told me to call you",
    "myname is priya",
    "i'm vikram and i want to know the price of the pro plan",
    "can i speak to meera from billing",
    "you are talking to deepak",
    "has Arjun Mehta checked in yet",
    "can priya pick up the order tomorrow",
    "i'm calling for my mother, kamala devi",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  for (const said of [
    "do you deliver in Hong Kong",
    "do you have a store in San Francisco",
    "how do i get to the Taj Mahal",
    "are trains running on Republic Day",
    "how much is a Big Mac",
    "what is the visa fee for Dubai",
    "are you open for Ramadan",
    "what's Dubai's visa policy",
    "what's the McDonald's breakfast time",
    "what time does the Domino's near the mall close",
    "where is the main branch",
    "what are the main office hours",
    "can i speak to someone in billing",
  ]) {
    await shared(said);
  }
  await keptPrivate("Main order kab aayega?");
});

test("rr 06: ids, addresses, disclosures and confirmations are private", async () => {
  for (const said of [
    "where is ord 7741", "status of #7741 please", "status of AB-7741 please", "is 4409 right",
    "ends in 09", "card number ends with four four", "i'm staying at room 512 of your hotel",
    "deliver to b-204 green park", "i live on elm street", "deliver to house number twelve, mg road",
    "calle mayor 10, madrid", "i think i have covid", "my mother has dementia, can i manage her account",
    "i use a wheelchair, is there a ramp", "my father is on dialysis, can we travel",
    "i'm having a panic attack", "i'm pregnent can i fly",
  ]) {
    await keptPrivate(said);
    assert.strictEqual(_isPersonal(said), true, said);
  }
  for (const said of ["oui c'est ça", "sim, está certo", "sounds right to me", "uh huh that's it"]) {
    await keptPrivate(said, "can you confirm your details");
  }
  for (const said of [
    "What happened in 1985?", "Is the 1,499 plan good for families?", "Do you have rooms for 4 people?",
    "Is the store open 24 hours?", "Do you deliver orders above 5000 rupees free?",
  ]) {
    await shared(said);
  }
});

test("rr 07: concurrent decides never share a turn, and empty is read-only and not enumerable", async () => {
  const session = sessionOn(new Store());
  const decisions = await Promise.all([
    session.decide("What are your opening hours?"),
    session.decide("What are your opening hours?"),
  ]);
  assert.deepStrictEqual(decisions.map((d) => d.turn).sort(), [1, 2]);

  const { decisions: answered } = await call(["What are your opening hours?"]);
  const decision = last(answered);
  assert.ok(!Object.keys(decision).includes("_empty"), Object.keys(decision).join(","));
  assert.ok(!JSON.stringify(decision).includes("_empty"));
  assert.strictEqual(decision.empty, false);
  assert.throws(() => { decision.empty = true; }, TypeError);
});

test("merge: outcome words agree with stored", async () => {
  const session = sessionOn(new Store());
  const old = await session.decide("What are your opening hours?");
  await session.decide("What is the refund policy?");
  assert.strictEqual(await session._recordModelTurn("What are your opening hours?", "Nine to five.", { turn: old.turn }), "interrupted");
  const decision = await session.answer("Do you deliver on Sundays?", () => "Yes, we do.");
  assert.strictEqual(decision.stored, true);
  assert.strictEqual(decision.notStored, "");
  const { decisions } = await call(["Is my order late?"]);
  assert.strictEqual(last(decisions).stored, false);
  assert.ok(last(decisions).notStored);
});
