"use strict";

// Emergencies, Hinglish place names, name structures and diagnoses (second re-review,
// 14 Oct 2026): the same cases as python/tests/test_voice_crisis_and_structures.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, _isPersonal } = require("./voice.js");

const ANSWER = "Here is the answer.";

class Store {
  constructor() {
    this.writes = [];
  }

  async cgetHit() {
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

const user = (content) => ({ role: "user", content });
const last = (list) => list[list.length - 1];

async function call(turns) {
  const store = new Store();
  const session = new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });
  const seen = [];
  const decisions = [];
  for (const said of turns) {
    decisions.push(await session.answer(said, (messages) => {
      seen.push(messages);
      return ANSWER;
    }));
  }
  return { store, decisions, seen };
}

async function keptPrivate(said) {
  const { store, decisions } = await call([said]);
  assert.strictEqual(last(decisions).cacheable, false, said);
  assert.ok(store.writes.every(([query]) => !query.includes(said)), said);
}

async function shared(said) {
  const { store, decisions } = await call([said]);
  assert.strictEqual(last(decisions).cacheable, true, said);
  assert.ok(store.writes.some(([q, a, t]) => q === said && a === ANSWER && !t), said);
}

test("an emergency in any of the callers' languages is private", async () => {
  for (const said of [
    "i don't want to live anymore",
    "i cut myself again last night",
    "quiero morir ya",
    "no quiero vivir mas",
    "não quero mais viver",
    "je veux mourir",
    "main marna chahta hoon",
    "jeena nahi chahti ab",
    "my brother is suicidal",
    "she keeps hurting herself and harming herself",
    "mere bete ne kerosene pee liya",
    "my toddler drank bleach",
    "mi hijo tragó una pila",
    "meu filho bebeu cloro",
    "he took a whole strip of tablets",
    "she overdosed on sleeping pills",
    "bhai ka accident ho gaya",
    "my dad fell down the stairs",
    "mi madre se cayó y está sangrando",
    "papa ko chot lagi hai, khoon nikal raha hai",
    "my wife got burned on the stove",
    "i was mugged outside the station",
    "meu pai sofreu um acidente",
    "papa behosh ho gaye",
    "my grandmother collapsed in the kitchen",
    "mi abuelo se desmayó",
    "mon père s'est évanoui",
    "he has chest pain and is sweating",
    "i think she is having a stroke",
    "dil ka daura pada hai",
    "he is not breathing properly"
  ]) {
    assert.strictEqual(_isPersonal(said), true, said);
    await keptPrivate(said);
  }
});

test("the next short turns after an emergency follow it", async () => {
  for (const turns of [
    ["mere bete ne kerosene pee liya", "ab kya karein"],
    ["bhai ka accident ho gaya", "kaunsa hospital paas mein hai"],
    ["mi hijo tragó una pila", "y ahora"],
    ["meu pai desmaiou", "e agora"],
    ["mon fils a avalé une pile", "et maintenant"],
    ["i don't want to live anymore", "is anyone there"],
    ["my dad fell down the stairs", "which hospital is closest", "what now"],
  ]) {
    const { store, decisions, seen } = await call(turns);
    assert.strictEqual(last(decisions).messages, null, turns.join(" >> "));
    assert.strictEqual(last(decisions).cacheable, false, turns.join(" >> "));
    assert.deepStrictEqual(last(seen)[0], user(turns[0]));
    assert.ok(store.writes.every(([q]) => turns.every((t) => !q.includes(t))), turns.join(" >> "));
  }
});

test("generic questions with emergency words stay shared", async () => {
  for (const said of [
    "Does the travel plan cover accidents?",
    "Do you sell batteries for the remote?",
    "Is there a first aid kit at the venue?",
    "Do you have a live chat on the website?",
    "Is the hospital cafeteria open on Sundays?",
    "What is the price of the burn cream?"
  ]) await shared(said);
});

test("hinglish places, festivals and brands are not people", async () => {
  for (const said of [
    "Durga Puja mein Kolkata mein delivery hoti hai?",
    "Chhath Puja pe Patna mein store khula hai?",
    "Karwa Chauth gift hampers available hain?",
    "Ganesh Chaturthi pe Mumbai mein offer hai kya?",
    "Hero Splendor on EMI milega?",
    "Royal Enfield ka service center Pune mein kahan hai?"
  ]) await shared(said);
});

test("names said through a structure in lower case are private", async () => {
  for (const said of [
    "booking sunita ke naam pe hai",
    "order vikas ke naam se hua tha",
    "anjali ka order kab aayega",
    "deepak ki booking confirm hai kya",
    "aqui é o joão",
    "sou a mariana, preciso de ajuda",
    "aqui é a ana falando",
    "can ramesh collect the parcel tomorrow",
    "could neha pick up my order",
    "nasci em 1987",
    "nací en 1990",
    "je suis amélie",
    "me llamo lucía"
  ]) {
    assert.strictEqual(_isPersonal(said), true, said);
    await keptPrivate(said);
  }
});

test("a first-person diagnosis is private whatever it is called", async () => {
  for (const said of [
    "i have lupus, can i fly",
    "i have crohns, is the meal plan ok",
    "tengo fibromialgia, puedo viajar",
    "tenho artrite, posso levar a bengala",
    "i was diagnosed with sarcoidosis last year",
    "i suffer from vertigo, which seat is best",
    "j'ai une endométriose"
  ]) {
    assert.strictEqual(_isPersonal(said), true, said);
    await keptPrivate(said);
  }
  for (const said of [
    "i have a question about the premium plan",
    "i have another question about delivery"
  ]) assert.strictEqual(_isPersonal(said), false, said);
});
