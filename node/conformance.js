"use strict";
// Phase 3: the scenarios every voice adapter must pass (fixtures/adapter-conformance.json),
// the Node twin of python/tests/conformance.py + conformance_drivers.py.
//
// A driver plays one call (a new session on a shared server) through its adapter: the
// custom loop on voiceSession().respond(), and LiveKit (withCrowkis on a real
// @livekit/agents Agent, when installed). The LLM and TTS are stand-ins that count their
// calls; the server is ConformanceStore (down / slow / audio_error, reworded questions) or,
// with CROWKIS_CONFORMANCE_SERVER=1, a real Crowkis server from the CROWKIS_* variables.
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { CrowkisClient } = require("./index.js");
const { voiceSession } = require("./voice.js");
const { waitForAudioStores } = require("./agent.js");
const { _waitForWrites: waitForWrites } = require("./voice.js");

const SPEC = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "adapter-conformance.json"), "utf8"));
const REAL = process.env.CROWKIS_CONFORMANCE_SERVER === "1";
const SLOW_MS = 2000;
const REAL_GAP_MS = 1500;
const RATE = 16000;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// A stand-in TTS's audio: the text itself, so a replayed clip says what it was of.
const audioOf = (text) => {
  const data = Buffer.from(text, "utf8");
  return data.length % 2 ? Buffer.concat([data, Buffer.alloc(1)]) : data;
};
const textOf = (audio) => Buffer.from(audio).toString("utf8").replace(/\0+$/, "");

// -- the server ---------------------------------------------------------------------------

class ConformanceStore {
  constructor({ server = "ok", aliases = {}, seed = {} } = {}) {
    this.server = server;
    this.aliases = { ...aliases };
    this.shared = new Map(Object.entries(seed));
    this.tool = new Map();
    this.writes = [];
    this.toolWrites = [];
    this.tenant = undefined;
    this._inFlight = new Set(); // the server's own work, waited for before the leak check
  }
  _work(fn) {
    const done = (async () => fn())();
    const tracked = done.catch(() => {}).finally(() => this._inFlight.delete(tracked));
    this._inFlight.add(tracked);
    return done;
  }
  async _fault(audio = false) {
    if (this.server === "down") throw Object.assign(new Error("connect ECONNREFUSED"), { code: "ECONNREFUSED" });
    if (this.server === "slow") await sleep(SLOW_MS);
    if (audio && this.server === "audio_error") throw new Error("audio cache error");
  }
  cgetHit(query, options = {}) {
    return this._work(async () => {
      await this._fault();
      if (options.template) return null;
      const found = this.shared.get(this.aliases[query] || query);
      if (found === undefined) return null;
      return { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
    });
  }
  cset(query, response, options = {}) {
    return this._work(async () => {
      await this._fault();
      this.writes.push([query, response, Boolean(options.template)]);
      if (!options.template) this.shared.set(query, response);
    });
  }
  ctoolget(tool, key) {
    return this._work(async () => {
      await this._fault(true);
      return this.tool.has(key) ? this.tool.get(key) : null;
    });
  }
  ctoolset(tool, key, value) {
    return this._work(async () => {
      await this._fault(true);
      this.toolWrites.push([JSON.parse(key), value]);
      this.tool.set(key, value);
    });
  }
  async idle() {
    while (this._inFlight.size) await Promise.allSettled([...this._inFlight]);
  }
  async close() {}
}

// A real client that also notes every write, so saved / neverSaved are checked against a
// real server too. Closed at the end of the scenario, not by each call.
class RecordingClient {
  constructor(client) {
    this.client = client;
    this.writes = [];
    this.toolWrites = [];
    return new Proxy(this, {
      get: (target, name) => {
        if (name in target) return target[name];
        const value = client[name];
        return typeof value === "function" ? value.bind(client) : value;
      },
    });
  }
  async cset(query, response, options = {}) {
    this.writes.push([query, response, Boolean(options.template)]);
    return this.client.cset(query, response, options);
  }
  async ctoolset(tool, key, value, options = {}) {
    this.toolWrites.push([key, value]);
    return this.client.ctoolset(tool, key, value, options);
  }
  async idle() {}
  async close() {} // shared by every call of the scenario
  async end() { await this.client.close(); }
}

const makeStore = (scenario) =>
  REAL ? new RecordingClient(new CrowkisClient()) : new ConformanceStore(scenario);
const agentId = () => (REAL ? `conformance-${crypto.randomBytes(5).toString("hex")}` : "conformance");

// -- drivers ------------------------------------------------------------------------------

class Counts {
  constructor() { this.llm = 0; this.tts = 0; }
}

const heard = (llm, tts, said, ms) => ({ llm, tts, heard: said, ms });

// A hand-written loop on voiceSession().respond(): cached audio is played, otherwise the
// text is streamed into the app's TTS; a barge-in calls cancel().
const customLoop = {
  name: "custom loop (voiceSession().respond)",
  supported: true,
  async call(store, turns, agent) {
    const counts = new Counts();
    const synthesise = async (text) => { counts.tts += 1; return audioOf(text); };
    const session = voiceSession({ client: store, agentId: agent, voice: "v", synthesise });
    const out = [];
    try {
      for (const turn of turns) {
        const [llm0, tts0] = [counts.llm, counts.tts];
        const started = performance.now();
        const llm = async function* () {
          counts.llm += 1;
          for (const piece of turn.reply) { await sleep(0); yield piece; }
        };
        const stream = await session.respond(turn.say, llm, { private: Boolean(turn.tool) });
        const parts = [];
        let spoke = false;
        if (stream.decision.audio) {
          parts.push(textOf(stream.decision.audio)); // the cached clip is played: no TTS
        } else {
          let index = 0;
          for await (const piece of stream) {
            if (turn.barge_in_after !== undefined && index >= turn.barge_in_after) {
              session.cancel(); // the caller talked over the answer
              break;
            }
            spoke = true;
            parts.push(piece);
            index += 1;
          }
        }
        await stream.close();
        counts.tts += spoke ? 1 : 0;
        out.push(heard(counts.llm > llm0, counts.tts > tts0, parts.join(""), performance.now() - started));
      }
    } finally {
      await session.agent.close();
    }
    return out;
  },
};

let lk = null;
let rtc = null;
try {
  lk = require("@livekit/agents");
  rtc = require("@livekit/rtc-node");
} catch {
  lk = null;
}

const streamOf = (items) =>
  new ReadableStream({
    async start(c) {
      for (const i of items) { await sleep(0); c.enqueue(i); }
      c.close();
    },
  });

async function readAll(stream) {
  const out = [];
  const reader = stream.getReader();
  for (let r = await reader.read(); !r.done; r = await reader.read()) out.push(r.value);
  return out;
}

const chunkText = (c) => (typeof c === "string" ? c : (c && c.delta && c.delta.content) || "");

// withCrowkis(agent) on a real @livekit/agents Agent; its own LLM and TTS nodes are the
// stand-ins (there is no room here).
const liveKit = {
  name: "LiveKit (withCrowkis)",
  supported: Boolean(lk),
  async call(store, turns, agentName) {
    const counts = new Counts();
    const state = { pieces: [], tool: false };
    const session = voiceSession({ client: store, agentId: agentName, voice: "v" });
    const agent = new lk.voice.Agent({ instructions: "You are Acme's assistant." });
    agent.llmNode = async (chatCtx) => {
      counts.llm += 1;
      if (state.tool && !chatCtx.items.some((i) => i.type === "function_call_output")) {
        return streamOf([{ id: "c", delta: { role: "assistant", toolCalls: [lk.llm.FunctionCall.create({ callId: "t1", name: "weather", args: "{}" })] } }]);
      }
      return streamOf(state.pieces);
    };
    agent.ttsNode = async (text) => {
      const pieces = [];
      for await (const p of text) pieces.push(p);
      const said = pieces.join("");
      if (said.trim()) counts.tts += 1;
      return streamOf([new rtc.AudioFrame(new Int16Array(audioOf(said).buffer.slice(0)), RATE, 1, audioOf(said).length / 2)]);
    };
    Object.defineProperty(agent, "tts", { get: () => ({ sampleRate: RATE, numChannels: 1, voice: "v" }) });
    const wrapped = require("./livekit.js").withCrowkis(agent, { crowkis: session });
    let items = [lk.llm.ChatMessage.create({ role: "system", content: ["You are Acme's assistant."] })];
    const out = [];
    for (const turn of turns) {
      const [llm0, tts0] = [counts.llm, counts.tts];
      Object.assign(state, { pieces: [...turn.reply], tool: Boolean(turn.tool) });
      items = [...items, lk.llm.ChatMessage.create({ role: "user", content: [turn.say] })];
      const started = performance.now();
      let said;
      if (turn.barge_in_after !== undefined) {
        // The caller talks over the reply: LiveKit stops reading it and cancels it.
        const reader = (await wrapped.llmNode(new lk.llm.ChatContext([...items]), {}, {})).getReader();
        const parts = [];
        for (let i = 0; i < turn.barge_in_after; i += 1) parts.push(chunkText((await reader.read()).value));
        await reader.cancel();
        said = parts.join("").trim();
      } else {
        if (turn.tool) {
          await this._reply(wrapped, new lk.llm.ChatContext([...items])); // the model calls the tool
          items = [...items,
            lk.llm.FunctionCall.create({ callId: "t1", name: "weather", args: "{}" }),
            lk.llm.FunctionCallOutput.create({ callId: "t1", name: "weather", output: "sunny", isError: false })];
        }
        said = await this._reply(wrapped, new lk.llm.ChatContext([...items]));
      }
      out.push(heard(counts.llm > llm0, counts.tts > tts0, said, performance.now() - started));
      items = [...items, lk.llm.ChatMessage.create({ role: "assistant", content: [said || "..."] })];
    }
    await session.agent.close();
    return out;
  },
  // One reply, as LiveKit runs it: llmNode's text into ttsNode.
  async _reply(agent, chatCtx) {
    const pieces = (await readAll(await agent.llmNode(chatCtx, {}, {}))).map(chunkText);
    async function* text() { for (const p of pieces) yield p; }
    const frames = await readAll(await agent.ttsNode(text(), {}));
    const said = pieces.join("").trim();
    // A cached clip replayed without the text: what the clip says.
    return said || textOf(Buffer.concat(frames.map((f) => Buffer.from(f.data.buffer))));
  },
};

const DRIVERS = [customLoop, liveKit];

// -- running and checking -----------------------------------------------------------------

async function settle(store) {
  await waitForWrites();
  await waitForAudioStores();
  await store.idle();
}

async function runScenario(driver, scenario, store) {
  const agent = agentId();
  const results = [];
  await settle(store);
  for (const turns of scenario.calls) {
    const copies = scenario.concurrent || 1;
    results.push(...(await Promise.all(Array.from({ length: copies }, () => driver.call(store, turns, agent)))));
    await settle(store); // writes and clips may finish in the background; the next caller is later
    if (REAL) await sleep(REAL_GAP_MS); // a real server makes a new answer findable within about a second
  }
  return results;
}

function check(assert, scenario, store, results) {
  const expected = scenario.calls.flatMap((turns) => Array.from({ length: scenario.concurrent || 1 }, () => turns));
  expected.forEach((turns, index) => {
    turns.forEach((turn, t) => {
      const got = results[index][t];
      const want = turn.expect;
      const where = `call ${index + 1}, ${JSON.stringify(turn.say)}: ${JSON.stringify(got)}`;
      // On a real server an earlier run may already have taught it this answer (its cache is
      // per tenant), so a miss is not required there; what the caller heard is.
      if (want.llm !== undefined && want.llm !== null && !(REAL && want.llm)) {
        assert.strictEqual(got.llm, want.llm, `LLM called? ${where}`);
      }
      if (want.tts !== undefined && want.tts !== null) assert.strictEqual(got.tts, want.tts, `TTS called? ${where}`);
      if (want.heard !== undefined) assert.strictEqual(got.heard.trim(), want.heard, `heard: ${where}`);
      if (want.max_ms !== undefined) assert.ok(got.ms < want.max_ms, `too slow: ${where}`);
    });
  });
  const writes = store.writes.filter((w) => !w[2]).map((w) => [w[0], w[1]]);
  const key = (w) => JSON.stringify(w);
  if (scenario.saved && !REAL) assert.deepStrictEqual(writes.map(key).sort(), scenario.saved.map(key).sort(), "shared writes");
  if (scenario.saved && REAL) {
    const allowed = new Set(scenario.saved.map(key));
    assert.ok(writes.every((w) => allowed.has(key(w))), `unexpected shared answers: ${JSON.stringify(writes)}`);
  }
  if (scenario.never_saved) {
    assert.ok(!JSON.stringify([store.writes, store.toolWrites]).includes(scenario.never_saved), "a private detail was written");
  }
}

// Sockets, servers and timers a scenario left behind (the leak check).
const resources = () =>
  process.getActiveResourcesInfo().filter((r) => r === "TCPSocketWrap" || r === "TCPServerWrap" || r === "Timeout");

module.exports = { SPEC, REAL, DRIVERS, makeStore, runScenario, check, resources, ConformanceStore };
