"use strict";
// The Node shared voice adapter layer (voiceTurns.js) does what the Python one does,
// scenario for scenario: fixtures/voice-turns-scenarios.json is written by the Python
// tests (python/tests/test_voice_turns.py), where the same scenarios are also checked
// against the Pipecat processors. Each is replayed here with the Node classes and the
// same small gate, and must end the same: store writes, clips kept, answer reports,
// transcript and served turns.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { Agent, waitForAudioStores } = require("./agent.js");
const { VoiceSession } = require("./voice.js");
const { AudioClips, AnswerPairing } = require("./voiceTurns.js");

const SCENARIOS = JSON.parse(
  fs.readFileSync(path.join(__dirname, "..", "fixtures", "voice-turns-scenarios.json"), "utf8")
);
const RATE = 16000;

class SceneStore {
  constructor(seed = {}) {
    this.shared = new Map(Object.entries(seed));
    this.tool = new Map();
    this.writes = [];
    this.toolWrites = [];
  }
  async cgetHit(query, options = {}) {
    const found = options.template ? undefined : this.shared.get(query);
    if (found === undefined) return null;
    return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }
  async cset(query, response, options = {}) {
    this.writes.push([query, response, Boolean(options.template)]);
    if (!options.template) this.shared.set(query, response);
  }
  async ctoolget(tool, key) {
    return this.tool.has(key) ? this.tool.get(key) : null;
  }
  async ctoolset(tool, key, value) {
    this.toolWrites.push([JSON.parse(key), value]);
    this.tool.set(key, value);
  }
  async close() {}
}

// A server with the Voice add-on: the audio cache keyed by text and labels.
class AddonStore extends SceneStore {
  constructor(seed) {
    super(seed);
    this.audio = new Map();
    this.audioWrites = [];
  }
  async caudioget(text, ...rest) {
    const labels = rest.slice(0, 4);
    return this.audio.get(JSON.stringify([text, ...labels])) || null;
  }
  async caudioset(text, ...rest) {
    const labels = rest.slice(0, 4);
    const clip = rest[4];
    const { ms } = rest[5] || {};
    this.audioWrites.push([text, labels, ms]);
    this.audio.set(JSON.stringify([text, ...labels]), Buffer.from(clip));
  }
}

async function runEvents(scenario) {
  const store = scenario.addon ? new AddonStore(scenario.seed) : new SceneStore(scenario.seed);
  const session = new VoiceSession(new Agent("caller", { client: store }), { voice: "v", ...(scenario.options || {}) });
  if (scenario.holds) {
    session.agent.decides = async () => true; // the server's decision engine holds new answers
    session.agent._holds = true;
  }
  const queue = !scenario.no_queue;
  const gate = queue ? { asked: [], question: "", messages: [] } : { question: "", messages: [] };
  const turns = [];
  const reports = [];
  const clips = new AudioClips(session, RATE);
  const pairing = new AnswerPairing(session, gate, clips, { onAnswer: async (info) => reports.push(info) });
  let serving = false;
  let modelTurn = false;
  for (const event of scenario.events) {
    switch (event.ev) {
      case "caller": {
        const said = event.said;
        gate.question = said;
        await pairing.callerMovedOn();
        const decision = await session.decide(said);
        const sharedAudio = decision.audioShareable;
        const audio = decision.needsModel || !sharedAudio ? null : await clips.get(decision.text);
        let messages = [{ role: "user", content: said }];
        if (decision.needsModel && decision.messages !== null) messages = decision.messages;
        gate.messages = [...messages];
        turns.push([decision.action, decision.text, audio !== null]);
        modelTurn = decision.needsModel;
        if (decision.needsModel) {
          if (queue) gate.asked.push(["caller", decision.turn, said, gate.messages]);
          break;
        }
        serving = true;
        if (audio) {
          clips.ttsAudio(audio); // the replayed clip passes the audio step
        } else {
          if (sharedAudio) clips.vouch(decision.text);
          pairing.speakRequested(decision.text);
        }
        break;
      }
      case "other_context":
        gate.question = "";
        modelTurn = false;
        gate.asked.push(null);
        break;
      case "tool_context":
        if (pairing.queueContext(event.messages)) await pairing.settle(true);
        break;
      case "start":
        await pairing.responseStart();
        break;
      case "text":
        pairing.responseText(event.t);
        break;
      case "end": {
        const todo = await pairing.responseEnd();
        if (todo) await pairing.record(...todo);
        break;
      }
      case "tool_call":
        pairing.toolCall();
        break;
      case "tools_done":
      case "tool_result_no_llm":
        pairing.toolsDone();
        await pairing.settle(true);
        break;
      case "expect":
        clips.expect(event.t, { shareable: event.shareable });
        break;
      case "tool_result":
        pairing.toolResult();
        break;
      case "interrupt":
        if (serving || modelTurn) session.cancel();
        if (queue) gate.asked.length = 0;
        serving = modelTurn = false;
        pairing.interrupted();
        await pairing.settle(false);
        clips.interrupted();
        break;
      case "bot_stopped":
        serving = modelTurn = false;
        break;
      case "speak":
        pairing.speakRequested(event.t);
        break;
      case "tts_start":
        clips.ttsStarted();
        break;
      case "tts_text":
        clips.ttsText(event.t);
        break;
      case "tts_audio":
        clips.ttsAudio(Buffer.from(event.b64, "base64"));
        break;
      case "tts_stop":
        await clips.ttsStopped();
        await waitForAudioStores(); // Voice add-on clips are stored in the background
        break;
      default:
        throw new Error(`unknown event ${event.ev}`);
    }
  }
  return {
    turns,
    writes: store.writes,
    clips: store.toolWrites,
    audio_clips: store.audioWrites || [],
    reports: reports.map(({ question, answer, saved, stored, notStored }) => ({
      question, answer, saved, stored, not_stored: notStored,
    })),
    transcript: session.transcript,
  };
}

test("the fixture holds the scenarios", () => {
  assert.ok(SCENARIOS.length >= 25);
});

for (const scenario of SCENARIOS) {
  test(`same as Python: ${scenario.name}`, async () => {
    assert.deepStrictEqual(await runEvents(scenario), scenario.expected);
  });
}
