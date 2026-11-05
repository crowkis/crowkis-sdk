"use strict";

// Replays the golden inputs through today's pipeline and records every decision (v4 P0).
// The Node twin of python/tests/golden/replay.py: the same calls, the same store groups,
// the same record per turn and the same counters (stats() keys in Python's names), so
// test-golden.js can check the files Python wrote.

const fs = require("node:fs");
const path = require("node:path");
const { Agent } = require("../src/client/agent.js");
const { VoiceSession } = require("../src/channels/voiceSession.js");

const GOLDEN = path.join(__dirname, "..", "..", "fixtures", "golden");
const INPUTS = JSON.parse(fs.readFileSync(path.join(GOLDEN, "inputs.json"), "utf8"));
const PHRASES = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "..", "fixtures", "voice-rule-phrases.json"), "utf8")).phrases;
const PHRASE_REPLY = "Here is the answer.";
const AGENT_ID = "golden";
const HIT_CONFIDENCE = 0.99;
const SUITE_STORE = "suite";
// stats() keys derived from the counts: left out, so they are compared as counts only.
const DERIVED_STATS = new Set(["cacheHitPct", "fillerHitPct", "modelCallsAvoidedPct"]);
// The one reason the two languages word differently (Python quotes the setting with repr()):
// mapped to Python's wording, so every other difference still fails the comparison.
const PYTHON_REASONS = new Map([
  [
    'the cached answer is a commitment (a price, a refund, a policy) and commitments="exact" does not allow speaking this match',
    "the cached answer is a commitment (a price, a refund, a policy) and commitments='exact' does not allow speaking this match",
  ],
]);
// The golden inputs name VoiceSession's options as Python does.
const VOICE_OPTION_NAMES = { short_turns: "shortTurns", share_templates: "shareTemplates", min_words: "minWords" };

// The server: an answer is found by its question (an "exact" hit) or by a reworded question in
// `aliases` (a "semantic" one), within one segment, shared answers and answer shapes apart, with
// the flags the server's decision engine sets. `engine`: whether that engine is on. `down`: every
// lookup and write fails, as an unreachable server.
class GoldenStore {
  constructor(seed, aliases, engine = false, pool = "") {
    this.down = false;
    this.engine = engine;
    this.aliases = new Map(Object.entries(aliases));
    this.answers = new Map();
    this.writes = [];
    for (const entry of seed) this.answers.set(GoldenStore._key(pool, entry.question, entry.template), entry);
  }

  async cgetHit(query, options = {}) {
    this._failIfDown();
    const asked = this.aliases.has(query) ? this.aliases.get(query) : query;
    const found = this.answers.get(GoldenStore._key(options.segment, asked, options.template));
    if (found === undefined) return null;
    return {
      response: Buffer.from(found.answer), text: found.answer, similarity: HIT_CONFIDENCE, ttlRemaining: 600,
      matchedKey: Buffer.from("k"), confidence: HIT_CONFIDENCE, hitType: asked === query ? "exact" : "semantic",
      vouched: Boolean(found.vouched), commitment: Boolean(found.commitment),
    };
  }

  async cset(query, response, options = {}) {
    this._failIfDown();
    const segment = options.segment || "";
    const template = Boolean(options.template);
    this.writes.push([segment, query, response, template]);
    this.answers.set(GoldenStore._key(segment, query, template), { question: query, answer: response });
  }

  async cdecision() {
    return { engine: this.engine };
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

function pythonName(name) {
  return name.replace(/[A-Z]/g, (letter) => `_${letter.toLowerCase()}`);
}

function voiceOptions(options = {}) {
  return Object.fromEntries(Object.entries(options).map(([name, value]) => [VOICE_OPTION_NAMES[name] || name, value]));
}

function sees(messages) {
  return messages === null || messages === undefined ? null : messages.map((m) => `${m.role}: ${m.content}`);
}

// One call through VoiceSession: decide each turn, record the reply when the model is asked
// (as a tool's result, or after the caller talked over it, when the turn says so).
class VoiceReplay {
  get pipeline() {
    return "voice";
  }

  // Where the seeded answers live: the one pool per tenant.
  get pool() {
    return "kb=1";
  }

  async call(store, call) {
    const options = { voice: "v", ...voiceOptions(call.options) };
    const session = new VoiceSession(new Agent(AGENT_ID, { client: store }), options);
    const turns = [];
    for (const turn of call.turns) turns.push(await VoiceReplay._turn(session, turn));
    const stats = Object.entries(session.stats()).filter(([name]) => !DERIVED_STATS.has(name));
    return { turns, stats: Object.fromEntries(stats.map(([name, value]) => [pythonName(name), value])) };
  }

  static async _turn(session, turn) {
    let decision = await session.decide(turn.say);
    const record = {
      say: turn.say, action: decision.action, rule: decision.rule,
      reason: PYTHON_REASONS.get(decision.reason) || decision.reason,
      cacheable: decision.cacheable, sees: sees(decision.messages),
    };
    if (decision.needsModel) {
      if (turn.barge_in) session.cancel();
      decision = await session.record(decision, turn.reply, { private: Boolean(turn.tool) });
      Object.assign(record, { stored: decision.stored, save_rule: decision.saveRule, not_stored: decision.notStored });
    } else {
      record.text = decision.text;
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

// Every call of a suite in order, a store per store group; what each call decided, and every
// write each store took.
async function replay(pipeline, calls) {
  const stores = new Map();
  const decisions = {};
  for (const call of calls) {
    const group = call.store || SUITE_STORE;
    if (!stores.has(group)) stores.set(group, new GoldenStore(call.seed || [], call.aliases || {}, Boolean(call.engine), pipeline.pool));
    const store = stores.get(group);
    store.down = Boolean(call.down);
    decisions[call.id] = await pipeline.call(store, call);
  }
  const writes = Object.fromEntries([...stores].map(([group, store]) => [group, store.writes]));
  return { calls: decisions, writes };
}

function goldenPath(pipeline, suite) {
  return path.join(GOLDEN, pipeline, `${suite}.json`);
}

module.exports = { VoiceReplay, goldenPath, replay, suites };
