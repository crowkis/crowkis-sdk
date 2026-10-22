"use strict";

// Replays the golden inputs through today's pipelines and records every decision (v4 P0).
// The Node twin of python/tests/golden/replay.py: the same calls, the same store, the
// same record per turn, so test-golden.js can check the files Python wrote.

const fs = require("node:fs");
const path = require("node:path");
const { Agent } = require("./agent.js");
const { VoiceSession } = require("./voice.js");
const { CallSession } = require("./session.js");
const { TurnFrame } = require("./turn.js");

const GOLDEN = path.join(__dirname, "..", "fixtures", "golden");
const INPUTS = JSON.parse(fs.readFileSync(path.join(GOLDEN, "inputs.json"), "utf8"));
const PHRASES = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "voice-rule-phrases.json"), "utf8")).phrases;
const PHRASE_REPLY = "Here is the answer.";
const AGENT_ID = "golden";
const HIT_CONFIDENCE = 0.99;

// The server: answers matched on the exact question within one segment, shared answers and
// answer shapes apart. `down`: every lookup and write fails, as an unreachable server.
class GoldenStore {
  constructor() {
    this.down = false;
    this.answers = new Map();
    this.writes = [];
  }

  async cgetHit(query, options = {}) {
    this._failIfDown();
    const found = this.answers.get(GoldenStore._key(options.segment, query, options.template));
    if (found === undefined) return null;
    return {
      response: Buffer.from(found), text: found, similarity: HIT_CONFIDENCE, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: HIT_CONFIDENCE, hitType: "semantic",
    };
  }

  async cset(query, response, options = {}) {
    this._failIfDown();
    const segment = options.segment || "";
    const template = Boolean(options.template);
    this.writes.push([segment, query, response, template]);
    this.answers.set(GoldenStore._key(segment, query, template), response);
  }

  async ctoolget() {
    return null;
  }

  async ctoolset() {}

  async close() {}

  _failIfDown() {
    if (this.down) {
      const error = new Error("crowkis server down");
      error.name = "ConnectionRefusedError";
      throw error;
    }
  }

  static _key(segment, query, template) {
    return JSON.stringify([segment || "", query, Boolean(template)]);
  }
}

// Chat's understanding step, answered from the frozen stand-in frames.
class ScriptedUnderstander {
  constructor(frames) {
    this.frames = frames;
  }

  understand(turn) {
    return TurnFrame.fromDict(this.frames[turn]);
  }
}

function sees(messages) {
  return messages === null || messages === undefined ? null : messages.map((m) => `${m.role}: ${m.content}`);
}

// One call through VoiceSession: decide each turn, record the reply when the model is asked.
class VoiceReplay {
  get pipeline() {
    return "voice";
  }

  async call(store, turns) {
    const session = new VoiceSession(new Agent(AGENT_ID, { client: store }), { voice: "v" });
    const records = [];
    for (const turn of turns) records.push(await VoiceReplay._turn(session, turn));
    return records;
  }

  static async _turn(session, turn) {
    let decision = await session.decide(turn.say);
    const record = {
      say: turn.say, action: decision.action, rule: decision.rule, reason: decision.reason,
      cacheable: decision.cacheable, sees: sees(decision.messages),
    };
    if (decision.needsModel) {
      decision = await session.record(decision, turn.reply);
      Object.assign(record, { stored: decision.stored, save_rule: decision.saveRule, not_stored: decision.notStored });
    } else {
      record.text = decision.text;
    }
    return record;
  }
}

// One call through CallSession: handle each turn, record the reply when the model is asked.
class ChatReplay {
  get pipeline() {
    return "chat";
  }

  async call(store, turns) {
    const session = new CallSession(new Agent(AGENT_ID, { client: store }), new ScriptedUnderstander(INPUTS.frames), {
      latencyBudgetMs: null, understandBudgetMs: null,
    });
    const records = [];
    for (const turn of turns) records.push(await ChatReplay._turn(session, turn));
    return records;
  }

  static async _turn(session, turn) {
    const result = await session.handle(turn.say);
    const verdict = result.verdict;
    const record = {
      say: turn.say, route: result.route, reason: result.reason, needs_model: result.needsModel,
      sees: sees(result.messages), key: verdict ? verdict.key : null, segment: verdict ? verdict.segment : null,
    };
    if (result.needsModel) {
      record.outcome = await session.recordAnswer(result, turn.reply);
    } else {
      record.text = result.text;
    }
    return record;
  }
}

// The 277 rule phrases, each said on its own by a new caller.
function phraseCalls() {
  return PHRASES.map((c) => ({ id: c.phrase, turns: [{ say: c.phrase, reply: PHRASE_REPLY }] }));
}

function suites() {
  return { phrases: phraseCalls(), ...INPUTS.suites };
}

// Every call of a suite in order on one store; what each turn decided, and every write.
async function replay(pipeline, calls) {
  const store = new GoldenStore();
  const decisions = {};
  for (const call of calls) {
    store.down = Boolean(call.down);
    decisions[call.id] = await pipeline.call(store, call.turns);
  }
  return { calls: decisions, writes: store.writes };
}

function goldenPath(pipeline, suite) {
  return path.join(GOLDEN, pipeline, `${suite}.json`);
}

module.exports = { ChatReplay, VoiceReplay, goldenPath, replay, suites };
