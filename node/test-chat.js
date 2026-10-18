"use strict";

// The chat caching report (16 Oct 2026), case by case, through Chat.turn. Mirrors
// python/tests/test_chat.py: the understanding model is scripted with the frames a good model
// returns; a model that drops a fact, or fails, must keep the turn private.
const assert = require("node:assert");
const { test } = require("node:test");
const { Chat, ChatConflict, MemoryStore } = require("./chat.js");
const { TurnFrame } = require("./turn.js");

const GENERAL = { kind: "general", subject: "none", confidence: 0.9 };

class SegmentedAgent {
  constructor() { this.store = new Map(); this.asked = []; this.saved = []; }
  async ask(key, options = {}) {
    this.asked.push([options.segment || null, key]);
    const answer = this.store.get(`${options.segment || ""}|${key}`);
    return answer ? { route: "cache", answer, confidence: 0.99 } : { route: "expensive" };
  }
  async learn(key, answer, options = {}) {
    this.store.set(`${options.segment || ""}|${key}`, answer);
    this.saved.push([options.segment || null, key, answer, options.ttl]);
  }
}

const scripted = (frames) => ({
  understand(turn) {
    const frame = frames[turn];
    if (frame instanceof Error) throw frame;
    return TurnFrame.fromDict(frame);
  },
});

function model(reply = "Here is the answer.") {
  const m = async (messages) => { m.read.push(messages); return typeof reply === "function" ? reply(messages) : reply; };
  m.read = [];
  return m;
}

async function run(frames, turns, { agent = new SegmentedAgent(), m = model(), ...options } = {}) {
  const chat = new Chat(agent, scripted(frames), { system: "You are Acme's assistant.", ...options });
  const history = [];
  const replies = [];
  for (const t of turns) {
    history.push({ role: "user", content: t });
    const reply = await chat.turn("thread-1", [...history], m);
    history.push({ role: "assistant", content: reply.text });
    replies.push(reply);
  }
  return { agent, m, replies };
}

const sharedQuestion = (m) => m.read[m.read.length - 1].slice(-1)[0].content;

test("1 allergy: the question carries it, the chat never reaches the model", async () => {
  const frames = {
    "I'm allergic to peanuts.": { kind: "personal", subject: "self", confidence: 0.9, entities: [{ text: "peanut allergy", type: "condition" }] },
    "Is pad thai safe to eat?": { ...GENERAL, question: "Is pad thai safe for someone with a peanut allergy?", entities: [{ text: "pad thai", type: "product", answer_relevant: true }] },
  };
  const agent = new SegmentedAgent();
  agent.store.set("kb=1;lang=und;channel=chat|Is pad thai safe to eat?", "Yes, generally safe.");
  const { m, replies } = await run(frames, Object.keys(frames), { agent });
  assert.notStrictEqual(replies[1].text, "Yes, generally safe.");
  assert.strictEqual(sharedQuestion(m), "Is pad thai safe for someone with a peanut allergy?");
  assert.deepStrictEqual(m.read[1].map((x) => x.role), ["system", "user"]);
  assert.strictEqual(agent.saved[agent.saved.length - 1][1], "Is pad thai safe for someone with a peanut allergy?");
});

test("1 a tailored answer never reaches someone who told nothing; another allergic user meets it", async () => {
  const frames = {
    "I'm allergic to peanuts.": { kind: "personal", subject: "self", confidence: 0.9, entities: [{ text: "peanut allergy", type: "condition" }] },
    "Is pad thai safe to eat?": { ...GENERAL, question: "Is pad thai safe for someone with a peanut allergy?" },
    "Is pad thai safe?": { ...GENERAL, question: "Is pad thai safe?" },
  };
  const agent = new SegmentedAgent();
  const chat = new Chat(agent, scripted(frames));
  const allergy = { role: "user", content: "I'm allergic to peanuts." };
  await chat.turn("allergic", [allergy], model());
  await chat.turn("allergic", [allergy, { role: "user", content: "Is pad thai safe to eat?" }], model("Avoid it."));
  assert.ok(agent.saved[agent.saved.length - 1][0].startsWith("kb=1;lang=und;channel=chat;told="));
  const plain = await chat.turn("plain", [{ role: "user", content: "Is pad thai safe?" }], model("Usually, yes."));
  assert.strictEqual(agent.asked[agent.asked.length - 1][0], "kb=1;lang=und;channel=chat");
  assert.strictEqual(plain.text, "Usually, yes.");
  await chat.turn("allergic-2", [allergy], model());
  const again = await chat.turn("allergic-2", [allergy, { role: "user", content: "Is pad thai safe to eat?" }], model());
  assert.ok(again.fromCache);
  assert.strictEqual(again.text, "Avoid it.");
});

test("1 a model that drops the allergy keeps the turn private", async () => {
  const frames = {
    "I'm allergic to peanuts.": { kind: "personal", subject: "self", confidence: 0.9 },
    "Is pad thai safe to eat?": { ...GENERAL, question: "Is pad thai safe to eat?" },
  };
  const { agent, m, replies } = await run(frames, Object.keys(frames));
  assert.strictEqual(replies[1].route, "agent");
  assert.strictEqual(m.read[1][0].content, "I'm allergic to peanuts.");
  assert.deepStrictEqual([agent.saved, agent.asked], [[], []]);
});

test("2-5 stated facts reach the question; the statement is never shared", async () => {
  const cases = [
    ["My mother has type 2 diabetes.", "What foods should be avoided?", "What foods should someone with type 2 diabetes avoid?", "condition", "type 2 diabetes"],
    ["I have a 3 year old daughter.", "What vaccines are due at this age?", "What vaccines are due for a 3 year old?", "quantity", "3 year old"],
    ["My son is 12 years old.", "What books should he read?", "What books should a 12 year old read?", "quantity", "12 years old"],
    ["I'm planning a trip to Goa in December.", "What should I pack?", "What should I pack for a trip to Goa in December?", "place", "Goa in December"],
  ];
  for (const [said, asked, question, type, text] of cases) {
    const frames = { [said]: { kind: "personal", subject: "self", confidence: 0.9, entities: [{ text, type }] }, [asked]: { ...GENERAL, question } };
    const { agent, m } = await run(frames, [said, asked]);
    assert.strictEqual(sharedQuestion(m), question, said);
    assert.strictEqual(agent.saved[agent.saved.length - 1][1], question, said);
    assert.ok(agent.saved.every((s) => s[1] !== said), said);
  }
});

test("a word the user never said keeps the question private", async () => {
  const frames = { "My son is 12 years old.": { kind: "personal", subject: "self", confidence: 0.9 }, "What books should he read?": { ...GENERAL, question: "What books suit a 12 year old?" } };
  const { agent } = await run(frames, Object.keys(frames));
  assert.deepStrictEqual(agent.saved, []);
});

test("6 the language is part of the segment", async () => {
  const frames = {
    "Reply only in Hindi from now on.": { kind: "dialogue", subject: "none", confidence: 0.9, language: "hi" },
    "What is the capital of Japan?": { ...GENERAL, question: "What is the capital of Japan?", language: "hi", entities: [{ text: "Japan", type: "place" }] },
  };
  const agent = new SegmentedAgent();
  agent.store.set("kb=1;lang=en;channel=chat|What is the capital of Japan?", "The capital of Japan is Tokyo.");
  const { m, replies } = await run(frames, Object.keys(frames), { agent, m: model("जापान की राजधानी टोक्यो है।") });
  assert.strictEqual(replies[1].text, "जापान की राजधानी टोक्यो है।");
  assert.ok(m.read[1][1].content.includes("Reply in this language: hi."));
  assert.strictEqual(agent.saved[agent.saved.length - 1][0], "kb=1;lang=hi;channel=chat");
});

test("7 two hops resolve through the last reply", async () => {
  const frames = {
    "What is the capital of France?": { ...GENERAL, question: "What is the capital of France?", entities: [{ text: "France", type: "place" }] },
    "What is its population?": { ...GENERAL, question: "What is the population of Paris?", uses_state: true },
    "And how far is it from London?": { ...GENERAL, question: "How far is Paris from London?", uses_state: true, entities: [{ text: "London", type: "place" }] },
  };
  const { agent } = await run(frames, Object.keys(frames), { m: model((msgs) => (msgs[msgs.length - 1].content.includes("capital") ? "Paris." : "About 2.1 million.")) });
  assert.deepStrictEqual(agent.saved.map((s) => s[1]), ["What is the capital of France?", "What is the population of Paris?", "How far is Paris from London?"]);
});

test("8 an unresolved follow-up stays private", async () => {
  const { agent } = await run({ "Compare it with the MacBook Air.": { kind: "dialogue", abstain: true, confidence: 0.3 } }, ["Compare it with the MacBook Air."]);
  assert.deepStrictEqual([agent.saved, agent.asked], [[], []]);
});

test("9 steps again is the earlier question, served from cache", async () => {
  const q = "How do I export data to CSV?";
  const frames = { "How do I export my data to CSV?": { ...GENERAL, question: q, entities: [{ text: "CSV", type: "topic" }] }, "What were the steps again?": { ...GENERAL, question: q, uses_state: true } };
  const { replies } = await run(frames, Object.keys(frames), { m: model("Open Data, then Export, then CSV.") });
  assert.ok(replies[1].fromCache);
});

test("10 booking steps are never shared", async () => {
  const frames = {
    "I want to change my flight.": { kind: "action", subject: "self", confidence: 0.9 },
    "The booking reference is K 7 D 9 2 X.": { kind: "dialogue", task_step: true, confidence: 0.9 },
    "Mumbai to Bangalore on the 14th.": { kind: "dialogue", task_step: true, confidence: 0.9 },
    "Move it to the 16th, evening.": { kind: "dialogue", task_step: true, confidence: 0.9 },
  };
  const { agent, m } = await run(frames, Object.keys(frames));
  assert.deepStrictEqual([agent.saved, agent.asked], [[], []]);
  assert.strictEqual(m.read[3][0].content, "I want to change my flight.");
});

test("every understanding failure keeps the turn private", async () => {
  const turn = "What is your refund policy?";
  for (const frame of [new Error("model down"), null, { kind: "general", confidence: 0.2, question: turn }, { abstain: true }]) {
    const { agent, replies } = await run({ [turn]: frame }, [turn]);
    assert.deepStrictEqual([agent.saved, agent.asked], [[], []]);
    assert.strictEqual(replies[0].text, "Here is the answer.");
  }
});

test("a word from a private turn is never in a shared answer", async () => {
  const frames = { "Hi, my name is Sarah and my order is 55512.": { kind: "personal", subject: "self", confidence: 0.9 }, "What is your refund policy?": { ...GENERAL, question: "What is your refund policy?" } };
  const { agent, replies } = await run(frames, Object.keys(frames), { m: model("Sarah, refunds take 30 days.") });
  assert.deepStrictEqual(agent.saved, []);
  assert.strictEqual(replies[1].outcome, "refused:private_word");
});

test("an emergency gets the business script and nothing is kept", async () => {
  const frames = { "My child swallowed bleach, what do I do?": { ...GENERAL, question: "What to do if a child swallows bleach?" } };
  const { agent, m, replies } = await run(frames, Object.keys(frames), { urgentReply: "Call 112 now. Poison helpline: 1800-116-117." });
  assert.strictEqual(replies[0].text, "Call 112 now. Poison helpline: 1800-116-117.");
  assert.deepStrictEqual([agent.saved, agent.asked, m.read], [[], [], []]);
});

test("the business's tools answer personal and live turns", async () => {
  const { agent, m, replies } = await run({ "What is my balance?": { kind: "live", subject: "self", confidence: 0.9 } }, ["What is my balance?"], { onTools: async () => "Your balance is ₹2,400." });
  assert.strictEqual(replies[0].text, "Your balance is ₹2,400.");
  assert.deepStrictEqual([agent.saved, m.read], [[], []]);
});

test("expiry follows the question type", async () => {
  const frames = { "Find hotels in Pune": { ...GENERAL, question: "What hotels are in Pune?", question_type: "search", entities: [{ text: "Pune", type: "place" }] }, "What is your refund policy?": { ...GENERAL, question: "What is your refund policy?", question_type: "policy" } };
  const { agent } = await run(frames, Object.keys(frames));
  assert.deepStrictEqual(agent.saved.map((s) => s[3]), [3600, undefined]);
});

test("two requests on one thread cannot overwrite each other", async () => {
  class Racing extends MemoryStore {
    load(threadId) { const [data, version] = super.load(threadId); super.save(threadId, data || {}, version); return [data, version]; }
  }
  const chat = new Chat(new SegmentedAgent(), scripted({ Hello: { kind: "chitchat", confidence: 0.9 } }), { store: new Racing() });
  await assert.rejects(chat.turn("t", [{ role: "user", content: "Hello" }], model()), ChatConflict);
});

test("damaged memory starts a fresh thread; threads are kept apart", async () => {
  const store = new MemoryStore();
  store.save("t", { state: "garbage", next_turn: "x" }, 0);
  const q = "What is your refund policy?";
  const chat = new Chat(new SegmentedAgent(), scripted({ [q]: { ...GENERAL, question: q }, "I'm allergic to peanuts.": { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  assert.strictEqual((await chat.turn("t", [{ role: "user", content: q }], model())).outcome, "saved");
  await chat.turn("a", [{ role: "user", content: "I'm allergic to peanuts." }], model());
  assert.strictEqual((await chat.turn("b", [{ role: "user", content: q }], model("Refunds take 30 days."))).outcome, "served");
});

// --- review findings ----------------------------------------------------------------------

test("a language asked for once stays when later turns are in English", async () => {
  const frames = {
    "Reply only in Hindi from now on.": { kind: "dialogue", confidence: 0.9, language: "hi" },
    "What is the capital of Japan?": { ...GENERAL, question: "What is the capital of Japan?", language: "en", entities: [{ text: "Japan", type: "place" }] },
  };
  const { agent, m } = await run(frames, Object.keys(frames));
  assert.strictEqual(agent.saved[agent.saved.length - 1][0], "kb=1;lang=hi;channel=chat");
  assert.ok(m.read[1][1].content.includes("Reply in this language: hi."));
});

test("a language is only ever a language tag; a segment value cannot add a field", () => {
  for (const raw of ["en;told=1", "hindi (devanagari) please", "en;region=goa", "x".repeat(40)]) {
    assert.strictEqual(TurnFrame.fromDict({ language: raw }).language, null, raw);
  }
  assert.strictEqual(TurnFrame.fromDict({ language: "pt-BR" }).language, "pt-br");
  const { RuleChecker } = require("./verify.js");
  assert.strictEqual(new RuleChecker().buildSegment({ region: "goa;told=1", segment: "a=b" }, "hi"),
    "kb=1;lang=hi;region=goa_told_1;segment=a_b;channel=chat");
});

test("a fact in the first question tailors it; peanut and shellfish never meet", async () => {
  const q = "Is pad thai safe for someone with a peanut allergy?";
  const first = await run({ [q]: { ...GENERAL, question: q, entities: [{ text: "peanut allergy", type: "condition" }] } }, [q]);
  assert.ok(first.agent.saved[0][0].includes(";told="));
  const asked = async (fact) => {
    const frames = {
      [`I'm allergic to ${fact}.`]: { kind: "personal", subject: "self", confidence: 0.9, entities: [{ text: `${fact} allergy`, type: "condition" }] },
      "Is pad thai safe to eat?": { ...GENERAL, question: `Is pad thai safe for someone with a ${fact} allergy?` },
    };
    const { agent } = await run(frames, Object.keys(frames));
    return agent.saved[agent.saved.length - 1][0];
  };
  assert.notStrictEqual(await asked("peanut"), await asked("shellfish"));
  assert.strictEqual(await asked("peanut"), await asked("peanut"));
});

test("one fact said two ways meets the same answers", async () => {
  const asked = async (said, question) => {
    const frames = { [said]: { kind: "personal", subject: "self", confidence: 0.9 },
      "Is pad thai safe to eat?": { ...GENERAL, question } };
    const { agent } = await run(frames, Object.keys(frames));
    return agent.saved[agent.saved.length - 1][0];
  };
  const peanut = "Is pad thai safe for someone with a peanut allergy?";
  assert.strictEqual(await asked("I'm allergic to peanuts.", peanut), await asked("I have a peanut allergy.", peanut));
  const diabetes = "Is pad thai safe to eat for someone with diabetes?";
  assert.strictEqual(await asked("I'm diabetic.", diabetes), await asked("I have diabetes.", diabetes));
  // Must still work: different facts never meet.
  assert.notStrictEqual(await asked("I have diabetes.", diabetes), await asked("I have a peanut allergy.", peanut));
});

test("an information question is neither an emergency nor a fact about the user", async () => {
  const q = "What are the symptoms of a heart attack?";
  const frames = { [q]: { ...GENERAL, question: q }, "What is your refund policy?": { ...GENERAL, question: "What is your refund policy?" } };
  const { replies } = await run(frames, Object.keys(frames), { urgentReply: "Call 112." });
  assert.strictEqual(replies[0].route, "shared");
  assert.strictEqual(replies[1].outcome, "saved");
});

test("damaged saved memory never breaks a thread; content parts and any thread id work", async () => {
  const q = "What is your refund policy?";
  for (const damaged of [{ state: { attributes: [1, 2] } }, { state: { facts: 5, private_words: 7, stated: "abc" } },
    { next_turn: Infinity }, { state: null }, "garbage", { state: { stated: [1, null, {}] } }]) {
    const store = new MemoryStore();
    store.save("t", damaged, 0);
    const chat = new Chat(new SegmentedAgent(), scripted({ [q]: { ...GENERAL, question: q } }), { store });
    assert.strictEqual((await chat.turn("t", [{ role: "user", content: q }], model())).outcome, "saved", JSON.stringify(damaged));
  }
  const chat = new Chat(new SegmentedAgent(), scripted({ [q]: { ...GENERAL, question: q } }));
  assert.strictEqual((await chat.turn(42, [{ role: "user", content: [{ type: "text", text: q }] }], model())).outcome, "saved");
});

test("unrelated threads do not wait for each other; no queue is kept afterwards", async () => {
  const q = "What is your refund policy?";
  const chat = new Chat(new SegmentedAgent(), scripted({ [q]: { ...GENERAL, question: q } }));
  const slow = async () => { await new Promise((r) => setTimeout(r, 300)); return "Refunds take 30 days."; };
  const started = Date.now();
  await Promise.all([0, 1, 2, 3].map((n) => chat.turn(`t${n}`, [{ role: "user", content: q }], slow)));
  assert.ok(Date.now() - started < 900, "four threads ran one after another");
  await new Promise((r) => setImmediate(r));
  assert.strictEqual(chat._queues.size, 0);
});

test("a one-word fact is kept and carried", async () => {
  for (const [fact, said, question] of [["I'm diabetic.", "What foods should I avoid?", "What foods should someone who is diabetic avoid?"],
    ["I'm vegan.", "What can I cook tonight?", "What can a vegan cook tonight?"]]) {
    const frames = { [fact]: { kind: "personal", subject: "self", confidence: 0.9 },
      [said]: { ...GENERAL, question } };
    const { replies } = await run(frames, Object.keys(frames));
    const last = replies[replies.length - 1];
    assert.deepStrictEqual([last.route, last.outcome], ["shared", "saved"], fact);
  }
  // Deliberate: a later question that does not carry the fact stays private (fixed code cannot
  // tell it is unrelated), so a dropped fact costs a hit, never a wrong answer.
  const frames = { "I'm diabetic.": { kind: "personal", subject: "self", confidence: 0.9 },
    "How do I reset a password?": { ...GENERAL, question: "How do I reset a password?" } };
  const { replies } = await run(frames, Object.keys(frames));
  assert.strictEqual(replies[replies.length - 1].route, "agent");
});

test("what the question already says does not split the cache", async () => {
  const france = { region: { value: "France", normalised: "france", changes_answer: true } };
  let frames = { "What is the capital of France?": { ...GENERAL, question: "What is the capital of France?", attributes: france, entities: [{ text: "France", type: "place" }] },
    "Which city is the capital of France?": { ...GENERAL, question: "Which city is the capital of France?", entities: [{ text: "France", type: "place" }] } };
  let { agent } = await run(frames, Object.keys(frames), { m: model("The capital of France is Paris.") });
  assert.deepStrictEqual(agent.saved.map((s) => s[0]), Array(2).fill("kb=1;lang=und;channel=chat"));
  // Must still work: a region the question does not say is the user's own and stays in the key.
  frames = { "Which laptops are in stock?": { ...GENERAL, question: "Which laptops are in stock?",
    attributes: { region: { value: "Pune", normalised: "pune", changes_answer: true } } } };
  ({ agent } = await run(frames, Object.keys(frames)));
  assert.strictEqual(agent.saved[0][0], "kb=1;lang=und;region=pune;channel=chat");
});

test("'this is' marks a name, not an ordinary word", async () => {
  const frames = { "This is the third time my order is late.": { kind: "personal", subject: "self", confidence: 0.9 },
    "How do I track an order?": { ...GENERAL, question: "How do I track an order?" } };
  const { replies } = await run(frames, Object.keys(frames), { m: model("Open the orders page and pick the order.") });
  assert.strictEqual(replies[replies.length - 1].outcome, "saved");
});

test("a thread memory stays small whatever is said or restored", async () => {
  const huge = "I'm allergic to " + "peanuts ".repeat(50000);
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({}), { store });
  for (let n = 0; n < 3; n++) await chat.turn("t", [{ role: "user", content: huge }], model("x ".repeat(50000)));
  assert.ok(JSON.stringify(store.load("t")[0]).length < 40000);
  const { CallState } = require("./callstate.js");
  const restored = CallState.fromDict({ stated: Array(50).fill(huge), last_reply: huge, active_question: huge });
  assert.ok(JSON.stringify(restored.toDict()).length < 40000);
});

test("memory keeps no name from a private reply", async () => {
  const said = "Where is my order?";
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ [said]: { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: said }], model("Sarah, order 555123 ships to sarah@example.com on Friday. Anything else?"));
  const kept = store.load("t")[0].state.last_reply;
  for (const p of ["sarah", "555123", "example"]) assert.ok(!kept.toLowerCase().includes(p), kept);
  assert.ok(kept.endsWith("?"), kept);
});

test("a lowercase name is private too", async () => {
  const frames = { "hi i'm sarah, where is my order?": { kind: "personal", subject: "self", confidence: 0.9 },
    "What is your refund policy?": { ...GENERAL, question: "What is your refund policy?" } };
  const { replies } = await run(frames, Object.keys(frames), { m: model("Sarah, refunds take 5 days.") });
  assert.strictEqual(replies[replies.length - 1].outcome, "refused:private_word");
});

test("a question with a private word is never shared", async () => {
  let frames = { "my name is sarah, where is my order?": { kind: "personal", subject: "self", confidence: 0.9 },
    "Is pad thai spicy for sarah?": { ...GENERAL, question: "Is pad thai spicy for sarah?" } };
  let { replies } = await run(frames, Object.keys(frames));
  assert.strictEqual(replies[replies.length - 1].route, "agent");
  // Must still work: a number the user told as a fact (an age) is carried on purpose.
  frames = { "I have a 3 year old daughter.": { kind: "personal", subject: "self", confidence: 0.9 },
    "What vaccines are due at this age?": { ...GENERAL, question: "What vaccines are due at age 3?" } };
  ({ replies } = await run(frames, Object.keys(frames)));
  assert.strictEqual(replies[replies.length - 1].route, "shared");
});

test("a generic word alone does not carry a specific fact", async () => {
  const said = "I'm allergic to penicillin.";
  for (const [question, route] of [["What can someone with allergies take for a sore throat?", "agent"],
    ["What can someone allergic to penicillin take for a sore throat?", "shared"]]) {
    const frames = { [said]: { kind: "personal", subject: "self", confidence: 0.9 },
      "What can I take for a sore throat?": { ...GENERAL, question } };
    const { replies } = await run(frames, Object.keys(frames));
    assert.strictEqual(replies[replies.length - 1].route, route, question);
  }
});

test("names in any script are masked in a private reply", async () => {
  const said = "Where is my order?";
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ [said]: { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: said }], model("Émile, Дмитрий and 王伟 will call you."));
  const kept = store.load("t")[0].state.last_reply;
  for (const name of ["Émile", "Дмитрий", "王伟"]) assert.ok(!kept.includes(name), kept);
});

test("only a region the question says word for word leaves the key", async () => {
  const frames = { "Do you sell Jordans?": { ...GENERAL, question: "Do you sell Jordans?", entities: [{ text: "Jordans", type: "product" }],
    attributes: { region: { value: "Jordan", normalised: "jordan", changes_answer: true } } } };
  const { agent } = await run(frames, Object.keys(frames));
  assert.strictEqual(agent.saved[0][0], "kb=1;lang=und;region=jordan;channel=chat");
  // The place the question names keeps it apart by itself, however the model wrote the region.
  const goa = { "What should I pack for Goa?": { ...GENERAL, question: "What should I pack for Goa?", entities: [{ text: "Goa", type: "place" }],
    attributes: { region: { value: "Goa, India", normalised: "goa, india", changes_answer: true } } } };
  const second = await run(goa, Object.keys(goa));
  assert.strictEqual(second.agent.saved[0][0], "kb=1;lang=und;channel=chat");
});

test("memory counts characters and digits the same in every SDK", async () => {
  const { CallState } = require("./callstate.js");
  assert.strictEqual(Array.from(CallState.fromDict({ last_reply: "\u{1F600}".repeat(1500) }).lastReply).length, 1000);
  const said = "I have a \u0967\u0968 year old son.";
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ [said]: { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: said }], model());
  assert.ok(store.load("t")[0].state.stated[0].includes("\u0967\u0968"));
});

test("a reply says why it was not shared", async () => {
  const frames = { "I'm allergic to peanuts.": { kind: "personal", subject: "self", confidence: 0.9 } };
  const { replies } = await run(frames, Object.keys(frames));
  assert.ok(replies[replies.length - 1].reason.includes("V3_not_general"), replies[replies.length - 1].reason);
});

test("every detail of a stated fact reaches the question", async () => {
  const said = "I'm planning a trip to Goa in December.";
  for (const [question, route] of [["What should I pack for a trip to Goa?", "agent"],
    ["What should I pack for a trip to Goa in December?", "shared"]]) {
    const frames = { [said]: { kind: "personal", subject: "self", confidence: 0.9, entities: [{ text: "Goa", type: "place" }] },
      "What should I pack?": { ...GENERAL, question } };
    const { replies } = await run(frames, Object.keys(frames));
    assert.strictEqual(replies[replies.length - 1].route, route, question);
  }
  // A name is not a detail the question must carry, and the memory keeps no detail as text.
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ "I'm Sarah and I'm allergic to peanuts.": {
    kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: "I'm Sarah and I'm allergic to peanuts." }], model());
  assert.ok(!JSON.stringify(store.load("t")[0]).toLowerCase().includes("sarah"));
});

test("review 3: names, details, lists, regions", async () => {
  const PERSONAL = { kind: "personal", subject: "self", confidence: 0.9 };
  const last = async (frames, opts) => { const { replies } = await run(frames, Object.keys(frames), opts); return replies[replies.length - 1]; };
  // 1. A name given in a turn that is itself shared is never in its answer, nor in a later question.
  let frames = { "Hi, I'm Sarah. What is the refund policy?": { ...GENERAL, question: "What is the refund policy?" },
    "Is pad thai spicy for sarah?": { ...GENERAL, question: "Is pad thai spicy for sarah?" } };
  const { replies } = await run(frames, Object.keys(frames), { m: model("Sarah, refunds take 5 days.") });
  assert.strictEqual(replies[0].outcome, "refused:private_word");
  assert.strictEqual(replies[1].route, "agent");
  const said = "I'm Sarah and I'm allergic to peanuts. What snacks are safe?";
  assert.strictEqual((await last({ [said]: { ...GENERAL, question: "What snacks are safe for Sarah who is allergic to peanuts?" } })).route, "agent");
  // 2. A name opening a sentence.
  assert.strictEqual((await last({ "Priya and I are allergic to nuts.": PERSONAL,
    "What snacks are safe?": { ...GENERAL, question: "What snacks are safe for Priya who is allergic to nuts?" } })).route, "agent");
  // 3. A place the model did not tag keeps the chat private: it is never dropped from the question.
  for (const question of ["What should I pack for a trip in December?", "What should I pack for a trip to Goa in December?"]) {
    assert.strictEqual((await last({ "I'm planning a trip to Goa in December.": PERSONAL,
      "What should I pack?": { ...GENERAL, question } })).route, "agent", question);
  }
  // 4. Every item of a list the user told is carried.
  for (const [question, route] of [["Which antibiotics can someone allergic to peanuts take?", "agent"],
    ["Which antibiotics can someone allergic to penicillin and peanuts take?", "shared"]]) {
    assert.strictEqual((await last({ "I'm allergic to penicillin and peanuts.": PERSONAL,
      "Which antibiotics can I take?": { ...GENERAL, question } })).route, route, question);
  }
  // 5. A region is dropped only when the question names all of it.
  const newYork = { region: { value: "New York", normalised: "new york", changes_answer: true } };
  frames = { "What new phones are in stock?": { ...GENERAL, question: "What new phones are in stock?", attributes: newYork } };
  const { agent } = await run(frames, Object.keys(frames));
  assert.strictEqual(agent.saved[0][0], "kb=1;lang=und;region=new york;channel=chat");
  // A number told in digits is carried by its word.
  assert.strictEqual((await last({ "I have a 3 year old daughter.": PERSONAL,
    "What vaccines are due at this age?": { ...GENERAL, question: "What vaccines are due for a three year old?" } })).route, "shared");
});

test("review 4: names in the question", async () => {
  const PERSONAL = { kind: "personal", subject: "self", confidence: 0.9 };
  const last = async (frames) => { const { replies } = await run(frames, Object.keys(frames)); return replies[replies.length - 1]; };
  // A capitalised word in a shared question must be something the model tagged as a place, thing or
  // topic, a month or day, or a word of the chat's earlier shared turns.
  assert.strictEqual((await last({ "My son Arjun is 12.": PERSONAL,
    "Books for him?": { ...GENERAL, question: "What books are good for Arjun who is 12?" } })).route, "agent");
  assert.strictEqual((await last({ "Can you help my colleague Priya with returns?": { ...GENERAL,
    question: "How do returns work for Priya?" } })).route, "agent");
  const france = [{ text: "France", type: "place" }];
  assert.strictEqual((await last({ "What is the capital of France?": { ...GENERAL,
    question: "What is the capital of France?", entities: france } })).route, "shared");
  assert.strictEqual((await last({ "What is the capital of France?": { ...GENERAL, question: "What is the capital of France?", entities: france },
    "What is its population?": { ...GENERAL, question: "What is the population of France?" } })).route, "shared");
  // A lowercase name given with a fact ("i'm sarah and ...") is a name.
  assert.strictEqual((await last({ "i'm sarah and i'm allergic to peanuts": PERSONAL,
    "What snacks are safe?": { ...GENERAL, question: "What snacks are safe for sarah who is allergic to peanuts?" } })).route, "agent");
  // Any shape of name the model did not tag: all capitals, mixed case, a sentence's first word, a script
  // without capitals. An acronym the model tagged is shared.
  for (const question of ["How do returns work for PRIYA?", "Can McKenzie return items?", "Priya can return items how?",
    "How do returns work for \u738b\u4f1f?"]) {
    assert.strictEqual((await last({ "Returns?": { ...GENERAL, question } })).route, "agent", question);
  }
  assert.strictEqual((await last({ "How do I enable SSO?": { ...GENERAL, question: "How do I enable SSO?",
    entities: [{ text: "SSO", type: "topic" }] } })).route, "shared");
  // "and I ..." starts a new clause, not a list: the allergy question is still shared.
  assert.strictEqual((await last({ "I'm allergic to peanuts and I live alone.": PERSONAL,
    "Is pad thai safe?": { ...GENERAL, question: "Is pad thai safe for someone allergic to peanuts?" } })).route, "shared");
});

test("a rewrite may add a question word, never a fact", async () => {
  const PERSONAL = { kind: "personal", subject: "self", confidence: 0.9 };
  const last = async (frames) => { const { replies } = await run(frames, Object.keys(frames)); return replies[replies.length - 1]; };
  // A word that could change what is asked ("avoid" for "good with", "cheapest", "safe") is never added.
  assert.strictEqual((await last({ "Which foods are good with gout?": { ...GENERAL, question: "Which foods should someone with gout avoid?" } })).route, "agent");
  assert.strictEqual((await last({ "What hotels are in Paris?": { ...GENERAL, question: "What are the cheapest hotels in Paris?",
    entities: [{ text: "Paris", type: "place" }] } })).route, "agent");
  // Exact words only: "tim" is not "time".
  assert.strictEqual((await last({ "Order 4 for tim, status?": { kind: "personal", subject: "other", confidence: 0.9 },
    "How long do refunds take?": { ...GENERAL, question: "How long do refunds take for tim?" } })).route, "agent");
  assert.strictEqual((await last({ "How many people live in Paris?": { ...GENERAL, question: "What is the population of Paris?",
    entities: [{ text: "Paris", type: "place" }] } })).route, "shared");
  // Must still work: a word that would tailor the answer, never said, keeps it private.
  assert.strictEqual((await last({ "What should I cook tonight?": { ...GENERAL, question: "What should a vegan cook tonight?" } })).route, "agent");
});

test("a name after a relation is a name whatever the model says", async () => {
  const frames = { "My colleague JOSE needs a refund.": { kind: "personal", subject: "other", confidence: 0.9,
    entities: [{ text: "JOSE", type: "product" }] },
  "How long do refunds take?": { ...GENERAL, question: "How long do refunds take for JOSE?", entities: [{ text: "JOSE", type: "product" }] } };
  const { replies } = await run(frames, Object.keys(frames));
  assert.strictEqual(replies[replies.length - 1].route, "agent");
  for (const [said, name] of [["My teacher Mr Smith asked about refunds.", "Smith"], ["My friend O'Brien wants a refund.", "Brien"],
    ["My wife's sister PRIYA needs a refund.", "PRIYA"], ["My son's teacher Ms RAO needs a refund.", "RAO"]]) {
    const wrongTag = [{ text: name, type: "product" }]; // the model mis-tags the name; fixed code must not
    const f = { [said]: { kind: "personal", subject: "other", confidence: 0.9, entities: wrongTag },
      "How long do refunds take?": { ...GENERAL, question: `How long do refunds take for ${name}?`, entities: wrongTag } };
    const r = await run(f, Object.keys(f));
    assert.strictEqual(r.replies[r.replies.length - 1].route, "agent", said);
  }
  // Must still work: a product or team name after a relation-like word is not a person.
  const support = { "Is Customer Support open on Sunday?": { ...GENERAL, question: "Is Customer Support open on Sunday?",
    entities: [{ text: "Customer Support", type: "topic" }] } };
  const s = await run(support, Object.keys(support));
  assert.strictEqual(s.replies[s.replies.length - 1].route, "shared");
});

test("memory keeps no email", async () => {
  const said = "I'm allergic to peanuts, email me at sarah@example.com";
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ [said]: { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: said }], model());
  const saved = JSON.stringify(store.load("t")[0]).toLowerCase();
  assert.ok(!saved.includes("sarah") && saved.includes("allergic"), saved);
});

test("memory keeps no name or long number and can be forgotten", async () => {
  const said = "Hi, I'm Sarah, my order 55512 arrived damaged.";
  const store = new MemoryStore();
  const chat = new Chat(new SegmentedAgent(), scripted({ [said]: { kind: "personal", subject: "self", confidence: 0.9 } }), { store });
  await chat.turn("t", [{ role: "user", content: said }], model());
  const saved = JSON.stringify(store.load("t")[0]);
  assert.ok(!saved.toLowerCase().includes("sarah") && !saved.includes("55512"), saved);
  await chat.forget("t");
  assert.deepStrictEqual(store.load("t"), [null, 0]);
});
