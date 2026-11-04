"use strict";
// A name the caller stated earlier in the call is never saved into a shared answer that repeats it
// (voice and Chat). Mirrors python/tests/test_stated_name.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { voiceSession } = require("./src/channels/voiceSession.js");
const { Chat } = require("./src/channels/chat.js");
const { statedNames } = require("./src/understanding/wordRules/personal.js");
const { TurnFrame } = require("./src/understanding/model/frame.js");
const { ConformanceStore } = require("./test/conformance.js");

const GENERAL = { kind: "general", subject: "none", confidence: 0.9 };
const INTRO_ANSWER = "Hi";
const INTROS = ["my name is Rahul Verma", "I'm Rahul Verma", "I am Rahul", "this is Rahul", "call me Rahul",
  "name's Rahul", "mera naam Rahul hai", "mera naam rahul verma hai"];
const LEAKS = ["Refunds in 7 days, Rahul.", "Sure Rahul, refunds take 7 days.", "Refunds in 7 days, rahul verma.",
  "Dear Mr Verma, refunds take 7 days."];
const nameIn = (answer) => ["rahul", "verma"].filter((w) => answer.toLowerCase().includes(w));
// An intro and a leaking answer that says a word of the name the intro gave.
const pairs = () => INTROS.flatMap((i) => LEAKS.filter((l) => nameIn(l).some((w) => i.toLowerCase().includes(w))).map((l) => [i, l]));
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function voice(turns) {
  const store = new ConformanceStore();
  const s = voiceSession({ client: store, agentId: "a", voice: null });
  for (const [said, answer] of turns) {
    const d = await s.decide(said);
    if (d.needsModel) await s.record(d, answer);
  }
  await sleep(500);
  return store.writes.filter((w) => w[2] === false).map((w) => w[0]); // keys of the shared answers saved
}

async function chat(intro, question, answer) {
  const frames = { [intro]: { kind: "personal", subject: "self", confidence: 0.9 }, [question]: { ...GENERAL, question } };
  const saved = [];
  const agent = {
    async ask() { return { route: "expensive" }; },
    async learn(key, text) { saved.push(text); },
  };
  const understander = { understand: (turn) => TurnFrame.fromDict(frames[turn]) };
  const c = new Chat(agent, understander, { system: "You are Acme's assistant." });
  const history = [];
  for (const [turn, reply] of [[intro, INTRO_ANSWER], [question, answer]]) {
    history.push({ role: "user", content: turn });
    const out = await c.turn("t", [...history], async () => reply);
    history.push({ role: "assistant", content: out.text });
  }
  return saved;
}

test("voice: an answer repeating a stated name is not shared", async () => {
  for (const [intro, leak] of pairs()) {
    assert.deepStrictEqual(await voice([[intro, INTRO_ANSWER], ["what is the refund policy", leak]]), [], `${intro} / ${leak}`);
  }
});

test("chat: an answer repeating a stated name is not shared", async () => {
  for (const [intro, leak] of pairs()) {
    assert.deepStrictEqual(await chat(intro, "what is the refund policy", leak), [], `${intro} / ${leak}`);
  }
});

test("control: a general answer is still saved", async () => {
  const answer = "Refunds take 7 days.";
  assert.deepStrictEqual(await voice([["my name is Rahul Verma", INTRO_ANSWER], ["what is the refund policy", answer]]), ["what is the refund policy"]);
  assert.deepStrictEqual(await chat("my name is Rahul Verma", "what is the refund policy", answer), [answer]);
});

test("control: a name the caller did not state is unaffected", async () => {
  const answer = "Dr Meera is available Monday.";
  assert.deepStrictEqual(await voice([["my name is Rahul Verma", INTRO_ANSWER], ["who is available on monday", answer]]), ["who is available on monday"]);
  assert.deepStrictEqual(await chat("my name is Rahul Verma", "who is available on monday", answer), [answer]);
});

test("control: not a name", async () => {
  for (const intro of ["I'm looking for the refund policy", "I am calling about refunds", "this is urgent", "I'm not sure",
    "this is the refund question"]) assert.deepStrictEqual([...statedNames([intro])], [], intro);
  const saved = await voice([["I'm looking for the refund policy", INTRO_ANSWER], ["what is the refund policy", "Refunds take 7 days."]]);
  assert.deepStrictEqual(saved, ["what is the refund policy"]);
});

test("names are read from the original case", () => {
  assert.deepStrictEqual([...statedNames(["my name is Rahul Verma"])].sort(), ["rahul", "verma"]);
  assert.deepStrictEqual([...statedNames(["I'm Priya, and I want a refund"])], ["priya"]);
  assert.deepStrictEqual([...statedNames(["mera naam Rahul hai"])], ["rahul"]);
});

test("lowercase names and trailing words", async () => {
  for (const intro of ["this is harpreet iyer calling", "I am harpreet iyer", "this is Harpreet Iyer calling"]) {
    const saved = await voice([[intro, "Noted."], ["how can I track a parcel", "Tracking links are sent when a parcel ships, harpreet iyer."]]);
    assert.deepStrictEqual(saved, [], intro);
    assert.deepStrictEqual([...statedNames([intro])].sort(), ["harpreet", "iyer"], intro);
  }
});

test("a phone said in words is not shared", async () => {
  const phone = "six seven zero eight six six eight one zero two";
  assert.deepStrictEqual(await voice([["my phone number is " + phone, "Noted."], ["how do I contact support", `Use the help centre or the support line, ${phone}.`]]), []);
  assert.deepStrictEqual(await voice([["my phone number is 6708668102", "Noted."], ["how do I contact support", `Call ${phone}.`]]), []);
});

test("control: ordinary number words are saved", async () => {
  const saved = await voice([["my phone number is six seven zero eight six six eight one zero two", "Noted."],
    ["what are your hours", "We are open from nine to six, Monday to Saturday."]]);
  assert.deepStrictEqual(saved, ["what are your hours"]);
});
