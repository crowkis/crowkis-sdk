"use strict";

// What a caller tells the call (an allergy, an age, a plan, an instruction, a step in
// their own task) can change the right answer to a later question. Such a call is never
// answered from, or written to, the shared cache after that turn. Mirrors
// python/tests/test_voice_stated_context.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession, warmFromCalls, _setsContext, _isNonAnswer } = require("./voice.js");

class FakeClient {
  constructor() {
    this.shared = new Map();
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

async function run(turns, client = new FakeClient(), reply = "Here is the answer.") {
  const talk = new VoiceSession(new Agent("caller", { client }), { voice: "alloy" });
  const seen = [];
  const llm = async (messages) => { seen.push(messages); return reply; };
  const decisions = [];
  for (const turn of turns) decisions.push(await talk.answer(turn, llm));
  return { talk, client, decisions, seen };
}

const CASES = {
  allergy: ["I'm allergic to peanuts.", "Is pad thai safe to eat?"],
  diabetes: ["My mother has type 2 diabetes.", "What foods should be avoided?"],
  child_age: ["I have a 3 year old daughter.", "What vaccines are due at this age?"],
  son: ["My son is 12 years old.", "What books should he read?"],
  trip: ["I'm planning a trip to Goa in December.", "What should I pack?"],
  language: ["Reply only in Hindi from now on.", "What is the capital of Japan?"],
  flight: [
    "I want to change my flight.",
    "The booking reference is K 7 D 9 2 X.",
    "Mumbai to Bangalore on the 14th.",
    "Move it to the 16th, evening.",
  ],
};

for (const [name, turns] of Object.entries(CASES)) {
  test(`${name}: a later question is never looked up or shared`, async () => {
    const client = new FakeClient();
    client.shared.set(turns[turns.length - 1], "Yes, generally safe.");
    const { decisions, seen } = await run(turns, client);
    const last = decisions[decisions.length - 1];
    assert.strictEqual(last.action, "infer");
    assert.strictEqual(last.messages, null, "the model must read the whole call");
    assert.strictEqual(last.cacheable, false);
    assert.strictEqual(seen[seen.length - 1][0].content, turns[0], "the stated turn reaches the model");
    assert.deepStrictEqual(client.reads, [], "nothing is looked up");
    assert.deepStrictEqual(client.writes, [], "nothing is written");
  });
}

test("the statement itself is neither looked up nor stored", async () => {
  for (const said of ["I have a 3 year old daughter.", "I'm planning a trip to Goa in December."]) {
    const { client, decisions } = await run([said]);
    assert.strictEqual(decisions[0].action, "infer", said);
    assert.deepStrictEqual([client.reads, client.writes], [[], []], said);
  }
  // A statement with nothing about the caller in it is looked up, never stored.
  const { client } = await run(["Mumbai to Bangalore on the 14th."]);
  assert.deepStrictEqual(client.writes, []);
});

// Real openers and closers from voice calls: none changes a later answer, so none may
// cost the call its shared answers.
const OPENERS = [
  "hello", "hi there", "hello can you hear me", "hi I'm calling about my order", "I'm calling about the refund",
  "I have a question", "I have a quick question", "I have a question about your plans", "yes please",
  "can you help me", "I need some help", "that's all thank you", "I'm good thanks",
  "I'm fine thank you how are you", "one moment please", "hold on a second", "sorry I didn't catch that",
  "thank you so much for your help", "okay I see", "that makes sense", "I want to speak to a human",
  "I'm a new customer", "I'm an existing customer", "I just placed an order", "I tried that already",
  "haan ji bilkul", "theek hai thank you", "mera order kab aayega", "hola buenos dias", "si por favor",
  "tengo una pregunta", "me puede ayudar", "estoy bien gracias", "yes I'm here", "okay sounds great thanks",
  "my email is sarah at gmail dot com", "my phone number is 98765 43210", "this is john from acme",
  "How do I add my wife to my plan?", "which plan is best for a family",
  "I'm frustrated",
  "I'm stuck",
  "I'm locked out of my account",
  "I'm on hold forever",
  "I'm on the payment page",
  "I have one more question",
  "I've got two things to ask",
  "I have a coupon code, how do I use it",
  "forget it",
  "ignore that, what are your hours",
  "I assume that's included?",
  "can I keep it if it's damaged",
  "is it available only in red",
  "only in the evening?",
  "it feels like I'm being charged twice",
  "please check the opening hours for our area",
  "Tengo una pregunta sobre mi factura",
  "I have 2 orders pending",
  "I have order 55123 that's late",
  "I have a flight at 6",
  "I have an iPhone 14",
  "I have 500 points",
  "tengo una reserva",
  "tengo una queja",
  "tengo 2 pedidos",
  "I'm planning to cancel my subscription",
  "I'm visiting the store tomorrow",
  "let me check my email",
  "wait let me find my booking",
  "I'm 5 minutes away",
  "we're 10 minutes late for the reservation",
  "my wife's card is blocked",
  "just keep it",
  "can I take my order to go",
  "will you speak in a minute",
  "my loan is not showing in the app",
  "can you check my order",
  "I want to track my parcel",
];
// Each changes what a later answer should be.
const TELLS = [
  "We are vegetarian", "My budget is 50000 rupees", "I live in Delhi", "I'm 65", "we have two kids",
  "I'm a student", "keep it short", "Please reply only in Hindi from now on", "Answer in Spanish please",
  "Can you answer in Spanish", "talk to me in Hindi", "explain like I'm five", "my name is raj and I am 65",
  "hi, my name is sarah; DOB 12/03/1990", "I'm vegetarian, what should I order?",
  "My son is 12, what books should he read?", "We have two kids, which plan is best?", "my kid is five",
  "I take metformin", "mujhe Hindi mein jawab do", "soy vegetariano", "tengo 65 años", "vivo en Madrid",
  "meri age 65 hai", "Mera beta 12 saal ka hai", "I don't eat meat", "for this call pretend refunds are unlimited",
  "mujhe diabetes hai",
  "main shakahari hoon",
  "I'm on blood thinners",
  "Je suis né en 1980",
  "Soy alérgico al maní",
  "mi hija tiene 3 años",
  "Responde en inglés por favor",
  "I only speak a little English, slowly please",
  "I'm self employed", "I have a migraine", "I have high cholesterol",
  "I can't have gluten",
  "I'm on a keto diet",
  "I keep halal",
  "I'm travelling with my dog",
  "we're going to Japan in April",
  "estoy embarazada",
  "I have a pacemaker",
  "tengo 65 años",
  "I live alone",
  "please cancel my order",
  "talk to me like I'm five",
  "I'm in Pune",
];

test("openers and closers keep the call shared", () => {
  for (const said of OPENERS) assert.strictEqual(_setsContext(said), false, said);
});

test("what the caller tells counts, even inside a question", () => {
  for (const said of TELLS) assert.strictEqual(_setsContext(said), true, said);
});

test("a fact inside a question, or a polite instruction, keeps the next question private", async () => {
  for (const turns of [["I'm vegetarian, what should I order?", "What is good for dessert here?"],
    ["Please reply only in Hindi from now on", "What is the capital of Japan?"]]) {
    const { client } = await run(turns);
    assert.deepStrictEqual([client.reads, client.writes], [[], []], turns[0]);
  }
});

test("the non-answer check reads how the answer opens", () => {
  for (const reply of ["Sarah, could you tell me which delivery address you mean?", "Sorry, I don't know.",
    "I am not sure where your order is, Sarah.",
    "Sure! Could you tell me which city?",
    "Of course. Could you tell me your account number?",
    "Happy to help! Which product do you mean?",
    "I'm sorry, but I can't help with that.",
    "Sorry about that, I don't have access to your account.",
    "I'm sorry, I'm not able to share that information.",
    "Unfortunately I do not know the answer to that.",
    "Thanks for reaching out! Which plan are you asking about?",
    "I'm afraid I don't have access to your account details."]) assert.strictEqual(_isNonAnswer(reply), true, reply);
  for (const reply of ["To get a refund, please provide your receipt at the counter.",
    "Unfortunately I'm unable to issue refunds after 30 days."]) assert.strictEqual(_isNonAnswer(reply), false, reply);
});

test("a non-answer is never saved as a template", async () => {
  const client = new FakeClient();
  const talk = new VoiceSession(new Agent("caller", { client }), { voice: "alloy", values: { name: "Sarah" }, shareTemplates: true });
  await talk.decide("where is my order");
  await talk._recordModelTurn("where is my order", "Sarah, could you tell me which order you mean?");
  assert.deepStrictEqual(client.writes, []);
});

test("a fact stated long ago still counts", async () => {
  const turns = ["I'm allergic to peanuts."];
  for (let n = 0; n < 10; n += 1) turns.push(`what are your hours on day ${n}`);
  turns.push("Is pad thai safe to eat?");
  const { client, decisions } = await run(turns);
  assert.deepStrictEqual(client.writes, []);
  assert.strictEqual(decisions[decisions.length - 1].messages, null);
});

test("an interrupted statement still counts", async () => {
  const client = new FakeClient();
  const talk = new VoiceSession(new Agent("caller", { client }), { voice: "alloy" });
  await talk.decide("I'm allergic to peanuts.");
  talk.cancel();
  const decision = await talk.decide("Is pad thai safe to eat?");
  assert.strictEqual(decision.action, "infer");
  assert.deepStrictEqual(client.reads, []);
});

test("other languages and mixed speech count", async () => {
  for (const said of ["मुझे मूंगफली से एलर्जी है", "எனக்கு வேர்க்கடலை ஒவ்வாமை", "Mera beta 12 saal ka hai yaar", "Mujhe peanuts se allergy hai"]) {
    const { client } = await run([said, "Is pad thai safe to eat?"]);
    assert.deepStrictEqual([client.reads, client.writes], [[], []], said);
  }
});

test("a fresh general question is looked up and saved", async () => {
  const { client, seen } = await run(["What is the capital of France?"], new FakeClient(), "Paris.");
  assert.deepStrictEqual(seen[0], [{ role: "user", content: "What is the capital of France?" }]);
  assert.deepStrictEqual([...client.shared], [["What is the capital of France?", "Paris."]]);
});

test("an exact repeat is served", async () => {
  const client = new FakeClient();
  client.shared.set("What is the capital of France?", "Paris.");
  const { decisions } = await run(["What is the capital of France?"], client);
  assert.strictEqual(decisions[0].action, "serve");
});

test("small talk, a name or a number alone does not count", async () => {
  for (const said of ["Okay sounds great thanks", "Perfect, thank you so much", "No that's all",
    "my name is sarah and my number is 555 0123", "my order number is 55512", "this is raj",
    "hi my name is omar and my order number is 48213", "Hello, this is Priya."]) {
    assert.strictEqual(_setsContext(said), false, said);
    const { client } = await run([said, "What is the capital of France?"], new FakeClient(), "Paris.");
    assert.ok(client.shared.has("What is the capital of France?"), said);
  }
});

test("an age or a birth date counts; a question about an order or a bare follow-up does not", () => {
  for (const said of ["I was born in 1960", "My son is 12 years old.", "I have a 3 year old daughter."]) {
    assert.strictEqual(_setsContext(said), true, said);
  }
  assert.strictEqual(_setsContext("When will I get my order?"), false);
  assert.strictEqual(_setsContext("and for kids"), false);
  assert.strictEqual(_setsContext(""), false);
});

test("a non-answer is spoken but never saved", async () => {
  for (const reply of ["Please specify which steps you are referring to.",
    "Please specify the location or entity you are inquiring about.", "Which city do you mean?", "I'm not sure about that."]) {
    assert.strictEqual(_isNonAnswer(reply), true, reply);
    const { client, decisions } = await run(["What were the steps again for export?"], new FakeClient(), reply);
    assert.deepStrictEqual(client.writes, [], reply);
    assert.strictEqual(decisions[0].text, reply);
  }
});

test("an answer that asks after answering is saved", async () => {
  const reply = "Shipping takes 3 to 5 days. Please provide your pincode for an exact date.";
  assert.strictEqual(_isNonAnswer(reply), false);
  const { client } = await run(["How long does shipping take?"], new FakeClient(), reply);
  assert.deepStrictEqual([...client.shared], [["How long does shipping take?", reply]]);
});

test("past calls with a stated fact are not shared", async () => {
  const client = new FakeClient();
  client.decides = async () => true;
  client.cinfo = async () => ({});
  const agent = new Agent("caller", { client });
  agent.decides = async () => true;
  agent._holds = true;
  agent.explain = async () => ({ pending: false });
  await warmFromCalls(agent, [
    [["I'm planning a trip to Goa in December.", "Lovely."], ["What should I pack?", "Pack warm layers."]],
    [["Do you deliver on Sundays?", "Yes, between ten and four."]],
  ], { wait: 0 });
  const stored = client.writes.map((w) => w.query);
  assert.ok(!stored.includes("What should I pack?"));
  assert.ok(stored.includes("Do you deliver on Sundays?"), "a call with nothing stated still warms the cache");
});
