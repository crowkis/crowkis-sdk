"use strict";
// A question must never be served the answer to a different question (Phase 5, N2).
// Mirrors python/tests/test_voice_different_question.py.
const assert = require("node:assert");
const { test, beforeEach } = require("node:test");
const { voiceSession, _differentSpecifics: differentSpecifics } = require("./voice.js");
const { waitForAudioStores } = require("./agent.js");
const { ConformanceStore } = require("./conformance.js");

const RIVERSIDE = "What time does the riverside greenhouse open on Sunday mornings?";
const RIVERSIDE_ANSWER = "The riverside greenhouse opens at nine on Sunday mornings.";

beforeEach(() => waitForAudioStores());

async function ask(store, question, reply = "From the model.") {
  const session = voiceSession({ client: store });
  const calls = [];
  const decision = await session.answer(question, async (m) => { calls.push(m); return reply; });
  await waitForAudioStores();
  return { decision, calls, session };
}

async function learned(aliases, question = RIVERSIDE, answer = RIVERSIDE_ANSWER) {
  const store = new ConformanceStore({ aliases });
  const { decision } = await ask(store, question, answer);
  assert.deepStrictEqual([decision.action, decision.stored], ["infer", true]);
  return store;
}

test("a question about something else is not served the stored answer", async () => {
  for (const asked of ["How late does the rooftop orchid greenhouse stay open on Sundays?",
    "What time does the riverside greenhouse open on Saturday mornings?",
    "What time does the city museum open on Sunday mornings?"]) {
    const store = await learned({ [asked]: RIVERSIDE });
    const { decision, calls, session } = await ask(store, asked);
    assert.strictEqual(decision.action, "infer", decision.reason);
    assert.match(decision.reason, /different question/);
    assert.strictEqual(calls.length, 1, "the model answers instead");
    assert.strictEqual(session.stats().differentQuestion, 1);
  }
});

test("must still work: a rewording is served", async () => {
  for (const [stored, asked] of [["how do I turn on dark mode", "how can I turn on dark mode"],
    ["what are your opening hours", "when are you open"],
    ["how do I reset my password", "how can I reset my password please"]]) {
    const store = await learned({ [asked]: stored }, stored, "Here is how.");
    const { decision, calls } = await ask(store, asked);
    assert.strictEqual(decision.action, "serve", decision.reason);
    assert.deepStrictEqual(calls, []);
  }
});

test("must still work: the same question is served", async () => {
  const store = await learned({});
  const { decision, calls } = await ask(store, RIVERSIDE);
  assert.deepStrictEqual([decision.action, calls.length], ["serve", 0]);
});

test("an answer saved without its question is served as before", async () => {
  const asked = "How late does the rooftop orchid greenhouse stay open on Sundays?";
  const store = new ConformanceStore({ aliases: { [asked]: RIVERSIDE }, seed: { [RIVERSIDE]: RIVERSIDE_ANSWER } });
  const { decision } = await ask(store, asked);
  assert.strictEqual(decision.action, "serve");
});

test("a record that cannot be read or written never breaks a turn", async () => {
  const asked = "How late does the rooftop orchid greenhouse stay open on Sundays?";
  const store = new ConformanceStore({ aliases: { [asked]: RIVERSIDE } });
  store.get = async () => { throw new Error("refused"); };
  store.set = async () => { throw new Error("refused"); };
  const first = await ask(store, RIVERSIDE, RIVERSIDE_ANSWER);
  assert.strictEqual(first.decision.stored, true);
  const { decision } = await ask(store, asked);
  assert.strictEqual(decision.action, "serve", "unknown means as before");
});

test("the rule itself, as in Python", () => {
  assert.strictEqual(differentSpecifics("hours on saturday", "hours on sunday"), true);
  assert.strictEqual(differentSpecifics("how can i turn on dark mode", "how do i turn on dark mode"), false);
  assert.strictEqual(differentSpecifics("when are you open", "what are your opening hours"), false);
  assert.strictEqual(differentSpecifics("", ""), false);
  assert.strictEqual(differentSpecifics("कब खुलता है", "कब खुलता है"), false);
});
