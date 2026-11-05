"use strict";

// F8 step 2: chat runs on the voice front end. voiceSession({channel: "chat"}) (one session per thread)
// and voiceSession() (a call) share one pool on one tenant, without and with a classifier and rewriter.
// The same cases as python/tests/test_chat_on_voice.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { voiceSession } = require("../src/channels/voiceSession.js");
const { WordRuleClassifier } = require("../src/understanding/slots.js");

const HOURS = "what are your opening hours on sunday";
const HOURS_ANSWER = "We open at 10 on Sundays.";
const TABLE = "| day | hours |\n| --- | --- |\n| sun | 10 |";
const PLANS = "which plans do you offer";

// One tenant's cache: exact matches per segment, shared by every session; `delay` slows a lookup.
class Tenant {
  constructor(delay = 0) {
    this.answers = new Map();
    this.writes = [];
    this.delay = delay;
    this.tenant = null;
  }

  async cgetHit(query, options = {}) {
    await new Promise((resolve) => setTimeout(resolve, this.delay));
    const found = this.answers.get(`${options.segment}|${query}`);
    if (found === undefined) return null;
    return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "exact" };
  }

  async cset(query, response, options = {}) {
    this.writes.push([options.segment, query, response]);
    this.answers.set(`${options.segment}|${query}`, response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}
}

// A rewriter that keys the one known phrasing on its verified question and keeps the caller's words otherwise.
const stubRewriter = { rewrite: (text, reading) => (!reading.isPersonal && text.toLowerCase().trim() === HOURS ? HOURS : null) };
const understood = () => ({ classifier: new WordRuleClassifier(), rewriter: stubRewriter });
const chat = (tenant, options) => voiceSession({ client: tenant, channel: "chat", ...options });
const call = (tenant, options) => voiceSession({ voice: "v", client: tenant, ...options });

async function say(session, text, answer) {
  const decision = await session.decide(text);
  if (decision.needsModel) await session.record(decision, answer);
  return decision;
}

// A model that repeats everything it was sent: the question alone, or the whole call.
async function askModel(session, text) {
  const decision = await session.decide(text);
  if (decision.needsModel) {
    const seen = decision.messages || session.transcript;
    await session.record(decision, "Noted: " + seen.map((m) => m.content).join(" / "));
  }
  return decision;
}

for (const [mode, makeOptions] of [["without an understander", () => ({}), ], ["with a classifier and rewriter", understood]]) {
  test(`${mode}: a general answer saved on chat is served on voice, and the reverse`, async () => {
    let tenant = new Tenant();
    await say(chat(tenant, makeOptions()), HOURS, HOURS_ANSWER);
    const heard = await call(tenant, makeOptions()).decide(HOURS);
    assert.deepStrictEqual([heard.action, heard.text], ["serve", HOURS_ANSWER]);
    tenant = new Tenant();
    await say(call(tenant, makeOptions()), HOURS, HOURS_ANSWER);
    const read = await chat(tenant, makeOptions()).decide(HOURS);
    assert.deepStrictEqual([read.action, read.text], ["serve", HOURS_ANSWER]);
  });

  test(`${mode}: a screen-only answer saved on chat is served on chat, not on voice`, async () => {
    const tenant = new Tenant();
    await say(chat(tenant, makeOptions()), PLANS, TABLE);
    assert.strictEqual((await chat(tenant, makeOptions()).decide(PLANS)).text, TABLE);
    const spoken = await call(tenant, makeOptions()).decide(PLANS);
    assert.deepStrictEqual([spoken.action, spoken.rule], ["infer", "ScreenOnlyAnswer"]);
  });

  test(`${mode}: the chat lookup budget is one second and voice keeps 250 ms`, async () => {
    const tenant = new Tenant(500);
    await say(chat(tenant, makeOptions()), HOURS, HOURS_ANSWER);
    assert.strictEqual(chat(tenant, makeOptions()).latencyBudgetMs, 1000);
    assert.strictEqual((await chat(tenant, makeOptions()).decide(HOURS)).action, "serve");
    assert.strictEqual((await call(tenant, makeOptions()).decide(HOURS)).action, "infer");
  });

  test(`${mode}: a detail stated in one thread never reaches the other channel`, async () => {
    for (const [sender, receiver] of [[chat, call], [call, chat]]) {
      const tenant = new Tenant();
      const thread = sender(tenant, makeOptions());
      await thread.decide("my name is Priya Sharma and my order number is 48213");
      await askModel(thread, HOURS);
      await askModel(thread, "where is my order 48213");
      const stored = JSON.stringify(tenant.writes).toLowerCase();
      for (const secret of ["priya", "48213"]) assert.ok(!stored.includes(secret), secret);
      const other = receiver(tenant, makeOptions());
      assert.strictEqual((await other.decide("where is my order 48213")).action, "infer");
      // What the other channel is served about a general question holds nothing the thread said.
      const served = ((await other.decide(HOURS)).text || "").toLowerCase();
      for (const secret of ["priya", "48213"]) assert.ok(!served.includes(secret), secret);
    }
  });

  test(`${mode}: a stated condition never reaches the other channel`, async () => {
    const tenant = new Tenant();
    const thread = chat(tenant, makeOptions());
    await thread.decide("i am allergic to peanuts");
    await askModel(thread, HOURS);
    assert.ok(!JSON.stringify(tenant.writes).toLowerCase().includes("peanuts"));
    assert.strictEqual((await call(tenant, makeOptions()).decide(HOURS)).action, "infer");
  });
}

// What Chat kept private that the voice word rules shared (v4-notes/f8-chat-replay.md): both channels.
const NAMES_A_PERSON = ["What did Priya order last week?", "Has Sarah paid yet?", "asks Anita about the refund policy",
  "Is the manager named Rahul in today?"];
const NAMES_NO_ONE = ["Do you ship to Australia?", "Is there a discount for Diwali?", "What is the capital of France?",
  "Can I pay with Apple Pay?", "Is the store open on Sunday?", "Are there flights for Goa?",
  "Does Netflix have a student plan?", "When did Apple release the iPhone 15?", "What does Mastercard charge for foreign transactions?", "Does Zomato deliver after midnight?", "Has Amazon Prime raised its price?", "What time does Walmart open on Sunday?"];
const REQUESTS = ["Add milk and eggs to my shopping list", "Remove the red shoes from my cart", "Put two tickets in my basket"];
const REQUEST_CONTROLS = ["How do I add an item to my cart?", "Can I add an item to my cart?"];
const URLS = ["what is on https://shop.example.com/track?id=abc", "is www.shop.example.com/x safe to open"];

async function messagesOf(text) {
  const out = [];
  for (const make of [call, chat]) out.push((await make(new Tenant()).decide(text)).messages);
  return out;
}

test("a question naming a person is not shared", async () => {
  for (const text of NAMES_A_PERSON) for (const messages of await messagesOf(text)) assert.strictEqual(messages, null, text);
});

test("must still work: a question naming no one is shared", async () => {
  for (const text of NAMES_NO_ONE) for (const messages of await messagesOf(text)) assert.notStrictEqual(messages, null, text);
});

test("an action request on the caller's things is not shared, whatever the answer says", async () => {
  for (const text of REQUESTS) for (const messages of await messagesOf(text)) assert.strictEqual(messages, null, text);
  for (const text of REQUEST_CONTROLS) for (const messages of await messagesOf(text)) assert.notStrictEqual(messages, null, text);
});

test("a question holding a link is not shared", async () => {
  for (const text of URLS) for (const messages of await messagesOf(text)) assert.strictEqual(messages, null, text);
});

test("a name the caller gave never reaches a shared answer, whatever the model knows", async () => {
  for (const make of [call, chat]) {
    const tenant = new Tenant();
    const thread = make(tenant);
    await thread.decide("this is Priya Sharma, my phone is 9876543210");
    await say(thread, HOURS, "Hello Priya Sharma, we open at 10 on Sundays.");
    assert.ok(!JSON.stringify(tenant.writes).toLowerCase().includes("priya"));
    assert.strictEqual((await make(tenant).decide(HOURS)).action, "infer");
  }
});

test("must still work: a clean answer after a private turn is saved", async () => {
  const tenant = new Tenant();
  const thread = chat(tenant);
  await thread.decide("this is Priya Sharma, my phone is 9876543210");
  await say(thread, HOURS, HOURS_ANSWER);
  assert.strictEqual((await call(tenant).decide(HOURS)).text, HOURS_ANSWER);
});
