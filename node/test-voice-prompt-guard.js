"use strict";
// An answer that repeats a caller's detail from the system prompt is never shared (same
// as python/tests/test_voice_prompt_guard.py; fixtures/prompt-guard-cases.json is shared
// by both). Covers answer({system}), record(decision, text, {system}), respond({system})
// and the shared adapter layer, which reads the system messages the model was sent.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { Agent } = require("./agent.js");
const { VoiceSession, _promptDetails, _repeatsPromptDetails, _resetPromptBaselines } = require("./voice.js");
const { AudioClips, AnswerPairing } = require("./voiceTurns.js");

const CASES = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "prompt-guard-cases.json"), "utf8"));
const PROMPT = CASES.prompt;

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

const sessionOn = (store) => new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });
const sorted = (set) => [...set].sort();

test("the details of a prompt, as in Python", () => {
  const { words, numbers } = _promptDetails(PROMPT);
  assert.deepStrictEqual([sorted(words), sorted(numbers)], [CASES.details.words, CASES.details.numbers]);
  for (const [prompt, wantWords, wantNumbers] of CASES.prompts) {
    const got = _promptDetails(prompt);
    assert.deepStrictEqual([sorted(got.words), sorted(got.numbers)], [wantWords, wantNumbers], prompt);
  }
});

test("which answers repeat a detail, as in Python", () => {
  for (const [answer, repeats] of CASES.answers) {
    assert.strictEqual(_repeatsPromptDetails(answer, CASES.question, PROMPT), repeats, answer);
  }
  assert.strictEqual(_repeatsPromptDetails("Hi Asha!", "hello this is Asha", PROMPT), false);
});

test("answer(), record() and respond() with a system prompt", async () => {
  _resetPromptBaselines();
  const store = new Store();
  const session = sessionOn(store);
  const hidden = await session.answer("what are your opening hours", async () => "Hi Asha! We open at nine.", { system: PROMPT });
  assert.strictEqual(hidden.stored, false);
  assert.match(hidden.notStored, /system prompt/);
  const shared = await session.answer("how do I reset my password", async () => "Open settings, then security.", { system: PROMPT });
  assert.strictEqual(shared.stored, true);
  const decision = await session.decide("how long does shipping take");
  await session.record(decision, "Asha, shipping takes three days.", { system: PROMPT });
  assert.strictEqual(decision.stored, false);
  const stream = await session.respond("what is your refund policy", () => ["Asha, refunds ", "take 30 days."], { system: PROMPT });
  for await (const piece of stream) assert.ok(piece);
  assert.strictEqual(stream.decision.stored, false);
  assert.deepStrictEqual(store.writes, [["how do I reset my password", "Open settings, then security.", false]]);
});

test("a plain system prompt changes nothing", async () => {
  const store = new Store();
  const d = await sessionOn(store).answer("what are your opening hours", async () => "Hi! We open at nine.", {
    system: "You are Acme's assistant. Be brief.",
  });
  assert.strictEqual(d.stored, true);
});

test("the shared adapter layer checks against the system messages the model read", async () => {
  const store = new Store();
  const session = sessionOn(store);
  const gate = { asked: [] };
  const pairing = new AnswerPairing(session, gate, new AudioClips(session, 16000));
  for (const [question, answer] of [
    ["what are your opening hours", "Hi Asha! We open at nine."],
    ["how do I reset my password", "Open settings, then security."],
  ]) {
    await pairing.callerMovedOn();
    const d = await session.decide(question);
    gate.asked.push(["caller", d.turn, question, [{ role: "system", content: PROMPT }, ...d.messages]]);
    await pairing.responseStart();
    pairing.responseText(answer);
    const todo = await pairing.responseEnd();
    await pairing.record(...todo);
  }
  assert.deepStrictEqual(store.writes, [["how do I reset my password", "Open settings, then security.", false]]);
});

test("numbers with commas or a country code, as in Python", () => {
  for (const [prompt, answers] of CASES.numbers) {
    for (const [answer, repeats] of answers) assert.strictEqual(_repeatsPromptDetails(answer, "q", prompt), repeats, answer);
  }
});

test("across calls, whatever differs between callers is a detail, as in Python", () => {
  _resetPromptBaselines();
  const { question, calls } = CASES.across_calls;
  for (const [prompt, answer, repeats] of calls) {
    assert.strictEqual(_repeatsPromptDetails(answer, question, prompt, ["t", "voice"]), repeats, answer);
  }
});

test("a business prompt never blocks sharing once it has varied; non-Latin names are caught", () => {
  _resetPromptBaselines();
  const key = ["t", "voice"];
  const base = (who) => `Always greet the customer warmly. You are Acme's assistant for customers of Acme Bank. Caller: ${who}`;
  _repeatsPromptDetails("x", "q", base("Asha"), key);
  assert.strictEqual(_repeatsPromptDetails("Always happy to help at Acme Bank.", "q", base("Ravi"), key), false);
  assert.strictEqual(_repeatsPromptDetails("Ravi, Acme Bank opens at nine.", "q", base("Ravi"), key), true);
  _resetPromptBaselines();
  const hindi = (who) => `Acme assistant. कॉलर: ${who}`;
  _repeatsPromptDetails("x", "q", hindi("आशा"), key);
  assert.strictEqual(_repeatsPromptDetails("रवि, we open at nine.", "q", hindi("रवि"), key), true);
});
