"use strict";

// Chat's `system` can carry one user's details ("The user is Asha Rao"). A shared answer
// that repeats them was shaped by that user and is never saved for everyone, as in voice
// (test-voice-prompt-guard.js). Mirrors python/tests/test_chat_prompt_guard.py.
const assert = require("node:assert");
const { test, beforeEach } = require("node:test");
const { Chat } = require("./chat.js");
const { CallSession } = require("./session.js");
const { TurnFrame } = require("./turn.js");
const { _resetPromptBaselines } = require("./voice.js");

beforeEach(() => _resetPromptBaselines()); // no other test's prompts remembered

const GENERAL = { kind: "general", subject: "none", confidence: 0.9 };
const QUESTION = "What time do you open?";
const FRAMES = { [QUESTION]: { ...GENERAL, question: QUESTION } };
const PERSONAL = "You are Acme's assistant. The user is Asha Rao, a Gold member since March.";
const PLAIN = "You are Acme's assistant. Be brief and friendly.";

class SegmentedAgent {
  constructor() { this.store = new Map(); this.saved = []; }
  async ask(key, options = {}) {
    const answer = this.store.get(`${options.segment || ""}|${key}`);
    return answer ? { route: "cache", answer, confidence: 0.99 } : { route: "expensive" };
  }
  async learn(key, answer, options = {}) {
    this.store.set(`${options.segment || ""}|${key}`, answer);
    this.saved.push([options.segment || null, key, answer]);
  }
}

const scripted = (frames) => ({ understand: (turn) => TurnFrame.fromDict(frames[turn]) });

async function turn(system, reply) {
  const agent = new SegmentedAgent();
  const read = [];
  const chat = new Chat(agent, scripted(FRAMES), { system });
  const result = await chat.turn("thread-1", [{ role: "user", content: QUESTION }], async (messages) => {
    read.push(messages);
    return reply;
  });
  return { agent, read, result };
}

test("an answer repeating a detail from the system prompt is never saved", async () => {
  for (const reply of ["Hi Asha! We open at nine.", "As a Gold member, you can come in from eight.", "Asha, we open at nine."]) {
    const { agent, read, result } = await turn(PERSONAL, reply);
    assert.strictEqual(result.text, reply, "the user still gets the answer");
    assert.strictEqual(result.outcome, "refused:prompt_detail", reply);
    assert.deepStrictEqual(agent.saved, []);
    assert.deepStrictEqual(read[0][0], { role: "system", content: PERSONAL });
  }
});

test("must still work: an answer without them is saved", async () => {
  const { agent, result } = await turn(PERSONAL, "We open at nine.");
  assert.strictEqual(result.outcome, "saved");
  assert.strictEqual(agent.saved.length, 1);
});

test("must still work: a prompt with no user details never blocks", async () => {
  for (const reply of ["Hi! We open at nine.", "Acme opens at nine."]) {
    const { agent, result } = await turn(PLAIN, reply);
    assert.strictEqual(result.outcome, "saved", reply);
    assert.strictEqual(agent.saved.length, 1);
  }
});

test("a call session without instructions is unchanged", () => {
  const session = new CallSession(new SegmentedAgent(), scripted(FRAMES));
  assert.strictEqual(session.instructions, "");
});
