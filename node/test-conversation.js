"use strict";

// Server-free tests for Conversation, the cache decisions every channel shares.
// Mirrors python/tests/test_conversation.py. Run: node --test test-conversation.js

const assert = require("node:assert");
const { test } = require("node:test");
const {
  Conversation, TurnPlan, FILLER, INTERRUPTED, KEPT, LOOKUP, MODEL, NON_ANSWER, NOT_SAVED, PRIVATE, SAVED, TEMPLATE,
} = require("./conversation.js");
const sdk = require("./index.js");

function turn(conv, said, answer) {
  return conv.settle(conv.plan(said), answer);
}

test("a general question is looked up and the model reads it alone", () => {
  const plan = new Conversation().plan("How long does shipping take?");
  assert.strictEqual(plan.action, LOOKUP);
  assert.strictEqual(plan.key, "How long does shipping take?");
  assert.deepStrictEqual(plan.messages, [{ role: "user", content: "How long does shipping take?" }]);
  assert.strictEqual(plan.shareable, true);
  assert.strictEqual(plan.personal, false);
  assert.strictEqual(plan.threshold, null);
  assert.strictEqual(plan.modelSees, "question");
});

test("a follow-up is keyed and read with the question before it", () => {
  const conv = new Conversation();
  turn(conv, "What is your return policy?", "You can return items within 30 days.");
  const plan = conv.plan("How long does it take?");
  assert.strictEqual(plan.action, LOOKUP);
  assert.strictEqual(plan.key, "What is your return policy? || How long does it take?");
  assert.deepStrictEqual(plan.messages.map((m) => m.content), ["What is your return policy?", "How long does it take?"]);
  assert.ok(plan.threshold !== null);
  assert.strictEqual(plan.modelSees, "question + previous");
});

test("a follow-up with nothing before it, or after a personal turn, is never shared", () => {
  const first = new Conversation().plan("How long does it take?");
  assert.deepStrictEqual([first.action, first.reason, first.key], [MODEL, "no_prior_turn", null]);
  const conv = new Conversation();
  turn(conv, "Where is my order?", "It ships today.");
  const plan = conv.plan("How long does it take?");
  assert.strictEqual(plan.messages, null);
  assert.strictEqual(plan.shareable, false);
  assert.strictEqual(plan.modelSees, "whole conversation");
});

test("personal turns: no values means no lookup; values mean an answer shape", () => {
  const plain = new Conversation().plan("I am a farmer, which schemes are best for me?");
  assert.deepStrictEqual([plain.action, plain.reason, plain.personal, plain.shareable], [MODEL, "personal_no_values", true, false]);
  const shaped = new Conversation({ values: { order_id: "A-1" } }).plan("When will my order arrive?");
  assert.deepStrictEqual([shaped.action, shaped.template, shaped.shareable], [LOOKUP, true, false]);
});

test("short, empty and filler turns; options are validated", () => {
  const conv = new Conversation({ fillers: { "thank you": "You're welcome." } });
  assert.strictEqual(conv.plan("").reason, "empty");
  assert.strictEqual(conv.plan("um okay").reason, "short");
  const filler = conv.plan("Thank you!");
  assert.deepStrictEqual([filler.action, filler.filler], [FILLER, "You're welcome."]);
  assert.throws(() => new Conversation({ minWords: 0 }));
  assert.throws(() => new Conversation({ maxTurns: 0 }));
});

test("settle: saved, private, template, non-answer, kept, not saved", () => {
  const saved = turn(new Conversation(), "How long does shipping take?", "Shipping takes 3 to 5 days.");
  assert.deepStrictEqual([saved.outcome, saved.key, saved.text, saved.write], [SAVED, "How long does shipping take?", "Shipping takes 3 to 5 days.", true]);
  assert.strictEqual(turn(new Conversation(), "Where is my order?", "It ships today.").outcome, PRIVATE);
  const tmpl = turn(new Conversation({ values: { order_id: "A-1001", eta: "Tuesday" } }), "When will my order arrive?", "Your order A-1001 arrives on Tuesday.");
  assert.deepStrictEqual([tmpl.outcome, tmpl.text, tmpl.template], [TEMPLATE, "Your order {order_id} arrives on {eta}.", true]);
  assert.strictEqual(turn(new Conversation(), "How much is shipping?", "Could you tell me the destination?").outcome, NON_ANSWER);
  assert.strictEqual(turn(new Conversation({ values: { order_id: "A-1001" } }), "How long does shipping take?", "For A-1001, shipping takes 3 days.").outcome, KEPT);
  const conv = new Conversation();
  assert.strictEqual(turn(conv, "shipping cost", "Shipping costs 5 dollars.").outcome, KEPT);
  assert.strictEqual(turn(conv, "How long does shipping take?", "  ").outcome, NOT_SAVED);
  assert.strictEqual(conv.settle(conv.unplanned("How long does shipping take?"), "Three days.").outcome, KEPT);
});

test("a personal turn reads the whole conversation; a general one reads nothing else", () => {
  const conv = new Conversation();
  turn(conv, "Hi, I'm Rahul and I'm a premium member.", "Hello Rahul.");
  assert.deepStrictEqual(conv.modelMessages(conv.plan("How long does shipping take?")), [
    { role: "user", content: "How long does shipping take?" },
  ]);
  assert.deepStrictEqual(conv.modelMessages(conv.plan("What's my name?"), "Be brief."), [
    { role: "system", content: "Be brief." },
    { role: "user", content: "Hi, I'm Rahul and I'm a premium member." },
    { role: "assistant", content: "Hello Rahul." },
    { role: "user", content: "What's my name?" },
  ]);
});

test("maxTurns caps the history a model call carries, not the transcript", () => {
  const conv = new Conversation({ maxTurns: 2 });
  for (let n = 0; n < 5; n += 1) turn(conv, `Where is my order number ${n}?`, `Order ${n} ships today.`);
  const messages = conv.modelMessages(conv.plan("What did I order last time?"));
  assert.strictEqual(messages.length, 2 * 2 + 1);
  assert.strictEqual(messages[0].content, "Where is my order number 3?");
  assert.strictEqual(conv.transcript.length, 10);
});

test("cache hits are remembered; unfillable shapes are not served; cancel rolls back", () => {
  const conv = new Conversation();
  const plan = conv.plan("What is your return policy?");
  assert.strictEqual(conv.served(plan, "30 days."), "30 days.");
  assert.strictEqual(conv.plan("How long does it take?").key, "What is your return policy? || How long does it take?");
  const shaped = new Conversation({ values: { order_id: "C-3" } });
  assert.strictEqual(shaped.served(shaped.plan("When will my order arrive?"), "Order {order_id} arrives {eta}."), null);
  assert.deepStrictEqual(shaped.transcript, []);
  const talk = new Conversation();
  turn(talk, "What is your return policy?", "30 days.");
  const open = talk.plan("How long does shipping take?");
  assert.strictEqual(talk.cancel(), true);
  assert.strictEqual(talk.cancel(), false);
  assert.strictEqual(talk.settle(open, "Three days.").outcome, INTERRUPTED);
  assert.strictEqual(talk.transcript.length, 2);
  talk.plan("How long does shipping take?");
  assert.strictEqual(talk.keepPrivate("How long does shipping take?", "Three days."), true);
  assert.strictEqual(talk.transcript.length, 4);
});

test("plans are frozen, and the SDK exports the policy and the rules", () => {
  const plan = new Conversation().plan("How long does shipping take?");
  assert.ok(plan instanceof TurnPlan);
  assert.throws(() => { plan.key = "x"; });
  assert.strictEqual(typeof sdk.Conversation, "function");
  assert.strictEqual(sdk.isPersonal("What did I order last time?"), true);
  assert.strictEqual(sdk.isContextDependent("how long does it take"), true);
  assert.strictEqual(sdk.isNonAnswer("I'm not sure, could you clarify?"), true);
});
