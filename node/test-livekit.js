"use strict";
// withCrowkis(agent): Crowkis in a LiveKit Agents (Node) agent (as python/tests/test_livekit.py).
// Run with real @livekit/agents types; the agent's LLM and TTS nodes are stand-ins, since
// there is no LiveKit room here. Skipped when @livekit/agents is not installed.
const test = require("node:test");
const assert = require("node:assert");

let lk;
let rtc;
try {
  lk = require("@livekit/agents");
  rtc = require("@livekit/rtc-node");
} catch {
  lk = null;
}
const { Agent: CrowkisAgent } = require("./agent.js");
const { VoiceSession, voiceSession } = require("./voice.js");

const QUESTION = "what is your refund policy";
const ANSWER = "Refunds take five business days.";
const PCM = new Int16Array(640).fill(513);
const skip = lk ? false : "@livekit/agents not installed";

class Store {
  constructor(seed = {}) {
    this.shared = new Map(Object.entries(seed));
    this.tool = new Map();
    this.writes = [];
    this.toolWrites = [];
    this.tenant = undefined;
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

const streamOf = (items) =>
  new ReadableStream({
    start(c) {
      for (const i of items) c.enqueue(i);
      c.close();
    },
  });

async function readAll(stream) {
  const out = [];
  const reader = stream.getReader();
  for (let r = await reader.read(); !r.done; r = await reader.read()) out.push(r.value);
  return out;
}

function ctx(turns, instructions = "You are Acme's assistant.") {
  const items = instructions ? [lk.llm.ChatMessage.create({ role: "system", content: [instructions] })] : [];
  for (const [role, text] of turns) items.push(lk.llm.ChatMessage.create({ role, content: [text] }));
  return new lk.llm.ChatContext(items);
}

// An agent whose own LLM / TTS nodes are stand-ins, wrapped with Crowkis.
function make({ reply = ANSWER, store = new Store(), session = null, voice = "rachel", toolFirst = false } = {}) {
  const fakes = { llmCalls: [], ttsCalls: [], tts: { sampleRate: 16000, numChannels: 1, voice } };
  const agent = new lk.voice.Agent({ instructions: "You are Acme's assistant." });
  agent.llmNode = async (chatCtx) => {
    fakes.llmCalls.push(chatCtx.items.map((i) => [i.role || i.type, i.textContent]));
    if (toolFirst && !chatCtx.items.some((i) => i.type === "function_call_output")) {
      return streamOf([{ id: "c", delta: { role: "assistant", toolCalls: [lk.llm.FunctionCall.create({ callId: "t1", name: "w", args: "{}" })] } }]);
    }
    return streamOf(reply.split(" ").map((w, i, all) => w + (i < all.length - 1 ? " " : "")));
  };
  agent.ttsNode = async (text) => {
    const pieces = [];
    for await (const p of text) pieces.push(p);
    fakes.ttsCalls.push(pieces.join(""));
    return streamOf([new rtc.AudioFrame(PCM, 16000, 1, PCM.length), new rtc.AudioFrame(PCM, 16000, 1, PCM.length)]);
  };
  Object.defineProperty(agent, "tts", { get: () => fakes.tts });
  const crowkis = session || new VoiceSession(new CrowkisAgent("caller", { client: store }), { voice: "v" });
  return { agent: require("./livekit.js").withCrowkis(agent, { crowkis }), store, session: crowkis, fakes };
}

// One reply: llmNode's text fed to ttsNode, as LiveKit does.
async function turn(agent, chatCtx) {
  const pieces = (await readAll(await agent.llmNode(chatCtx, {}, {}))).map((c) =>
    typeof c === "string" ? c : (c.delta && c.delta.content) || ""
  );
  async function* text() {
    for (const p of pieces) yield p;
  }
  const frames = await readAll(await agent.ttsNode(text(), {}));
  return { said: pieces.join("").trim(), frames };
}

test("a miss, then a hit spoken from the cache with its audio", { skip }, async () => {
  const { agent, store, fakes } = make();
  const first = await turn(agent, ctx([["user", QUESTION]]));
  assert.strictEqual(first.said, ANSWER);
  const again = await turn(agent, ctx([["user", QUESTION], ["assistant", ANSWER], ["user", QUESTION]]));
  assert.strictEqual(again.said, ANSWER);
  assert.strictEqual(fakes.llmCalls.length, 1); // the second time, no LLM
  assert.deepStrictEqual(fakes.ttsCalls.map((t) => t.trim()), [ANSWER]); // nor the TTS
  const replayed = Buffer.concat(again.frames.map((f) => Buffer.from(f.data.buffer, f.data.byteOffset, f.data.byteLength)));
  assert.strictEqual(replayed.length, PCM.byteLength * 2);
  assert.deepStrictEqual(store.writes, [[QUESTION, ANSWER, false]]);
  assert.strictEqual(store.toolWrites[0][0].format, "pcm16-16000");
});

test("the model reads the instructions and only the question", { skip }, async () => {
  const { agent, fakes } = make();
  await turn(agent, ctx([["user", "I am Priya, account 4471."], ["assistant", "Hello Priya."], ["user", QUESTION]]));
  assert.deepStrictEqual(fakes.llmCalls[0], [["system", "You are Acme's assistant."], ["user", QUESTION]]);
});

test("an answer is saved only once it has been spoken", { skip }, async () => {
  const { agent, store } = make();
  for await (const _ of await agent.llmNode(ctx([["user", QUESTION]]), {}, {})) {
    // a preemptive attempt LiveKit then discards: its TTS never runs
  }
  assert.deepStrictEqual(store.writes, []);
});

test("generateReply with instructions is not a caller turn", { skip }, async () => {
  const { agent, store, session, fakes } = make({ reply: "Goodbye, thanks for calling!" });
  const c = ctx([["user", QUESTION], ["assistant", ANSWER]]);
  c.items.push(lk.llm.ChatMessage.create({ role: "system", content: ["Say goodbye."] }));
  const { said } = await turn(agent, c);
  assert.strictEqual(said, "Goodbye, thanks for calling!");
  assert.strictEqual(fakes.llmCalls[0].length, 4);
  assert.strictEqual(session.stats().turns, 0);
  assert.deepStrictEqual(store.writes, []);
});

test("an answer after a tool's result stays in the call", { skip }, async () => {
  const { agent, store, session } = make({ reply: "It is sunny in Paris.", toolFirst: true });
  const q = "what is the weather in paris today";
  await turn(agent, ctx([["user", q]]));
  const c = ctx([["user", q]]);
  c.items.push(lk.llm.FunctionCall.create({ callId: "t1", name: "w", args: "{}" }));
  c.items.push(lk.llm.FunctionCallOutput.create({ callId: "t1", name: "w", output: "sunny", isError: false }));
  const { said } = await turn(agent, c);
  assert.strictEqual(said, "It is sunny in Paris.");
  assert.deepStrictEqual(store.writes, []);
  assert.strictEqual(session.transcript.at(-1).content, "It is sunny in Paris.");
});

test("RAG context means the whole context and no sharing", { skip }, async () => {
  const { agent, store, fakes } = make({ reply: "Refunds take 2 days for Gold members." });
  const c = ctx([["user", QUESTION]]);
  c.items.splice(1, 0, lk.llm.ChatMessage.create({ role: "system", content: ["Knowledge: Gold refunds take 2 days."] }));
  await turn(agent, c);
  assert.strictEqual(fakes.llmCalls[0].length, 3);
  assert.deepStrictEqual(store.writes, []);
});

test("a say() never plays another reply's cached audio", { skip }, async () => {
  const store = new Store({ [QUESTION]: ANSWER });
  const { agent, fakes } = make({ store });
  const key = JSON.stringify({ format: "pcm16-16000", language: "und", speed: "1", text: ANSWER, voice: "v" });
  store.tool.set(key, Buffer.from(PCM.buffer).toString("base64"));
  for await (const _ of await agent.llmNode(ctx([["user", QUESTION]]), {}, {})) {
    // a hit with audio, interrupted before its TTS ran
  }
  async function* line() {
    yield "Are you still there?";
  }
  await readAll(await agent.ttsNode(line(), {}));
  assert.deepStrictEqual(fakes.ttsCalls, ["Are you still there?"]);
});

test("an answer repeating a caller detail from the instructions stays private", { skip }, async () => {
  const { agent, store } = make({ reply: "Hi Asha! We open at nine." });
  await turn(agent, ctx([["user", "what are your opening hours"]], "You are Acme's assistant. The caller is Asha Rao, account 99812."));
  assert.deepStrictEqual(store.writes, []);
});

test("the voice comes from the TTS when the session has none, and follows a change", { skip }, async () => {
  const store = new Store();
  const session = voiceSession({ client: store });
  const { agent, fakes } = make({ store, session });
  await turn(agent, ctx([["user", QUESTION]]));
  fakes.tts.voice = "nova";
  await turn(agent, ctx([["user", "how do I reset my password"]]));
  assert.strictEqual(session.voice, "nova");
  assert.deepStrictEqual(store.toolWrites.map(([k]) => k.voice), ["rachel", "nova"]);
});

test("a reply cancelled while written saves nothing and frees its run", { skip }, async () => {
  const { agent, store } = make();
  const stream = await agent.llmNode(ctx([["user", QUESTION]]), {}, {});
  const reader = stream.getReader();
  await reader.read();
  await reader.cancel(); // the caller interrupted
  assert.deepStrictEqual(store.writes, []);
});

test("the agent's own ttsNode is given a ReadableStream, as LiveKit gives it", { skip }, async () => {
  const { agent, fakes } = make();
  let got = null;
  const own = agent.ttsNode;
  // Re-wrap a fresh agent whose own ttsNode reads its input with getReader().
  const { agent: other } = make();
  void own;
  other._probe = true;
  const base = new lk.voice.Agent({ instructions: "x" });
  base.llmNode = async () => streamOf([ANSWER]);
  base.ttsNode = async (text) => {
    got = text instanceof ReadableStream;
    const reader = text.getReader();
    while (!(await reader.read()).done);
    return streamOf([new rtc.AudioFrame(PCM, 16000, 1, PCM.length)]);
  };
  Object.defineProperty(base, "tts", { get: () => fakes.tts });
  require("./livekit.js").withCrowkis(base, { crowkis: new VoiceSession(new CrowkisAgent("c", { client: new Store() }), { voice: "v" }) });
  await turn(base, ctx([["user", QUESTION]]));
  assert.strictEqual(got, true);
});

test("cancelling a reply while a read is pending stops the LLM at once", { skip }, async () => {
  const { agent } = make();
  let innerCancelled = false;
  const agent2 = new lk.voice.Agent({ instructions: "x" });
  agent2.llmNode = async () =>
    new ReadableStream({
      start(c) {
        c.enqueue("Refunds ");
      },
      cancel() {
        innerCancelled = true;
      },
    });
  agent2.ttsNode = agent.ttsNode;
  Object.defineProperty(agent2, "tts", { get: () => ({ sampleRate: 16000, numChannels: 1, voice: "v" }) });
  require("./livekit.js").withCrowkis(agent2, { crowkis: new VoiceSession(new CrowkisAgent("c", { client: new Store() }), { voice: "v" }) });
  const stream = await agent2.llmNode(ctx([["user", QUESTION]]), {}, {});
  const reader = stream.getReader();
  await reader.read(); // "Refunds ", then the next read waits on the LLM
  const pendingRead = reader.read();
  const started = Date.now();
  await reader.cancel();
  await pendingRead.catch(() => {});
  assert.ok(Date.now() - started < 500);
  assert.strictEqual(innerCancelled, true);
});

test("with audio output off, answers are saved and hits are not rolled back", { skip }, async () => {
  const { agent, store, session } = make();
  Object.defineProperty(agent, "session", { get: () => ({ output: { audio: null, audioEnabled: false } }) });
  for await (const _ of await agent.llmNode(ctx([["user", QUESTION]]), {}, {})) {
    // no ttsNode runs: audio is off
  }
  assert.deepStrictEqual(store.writes, [[QUESTION, ANSWER, false]]);
  for await (const _ of await agent.llmNode(ctx([["user", QUESTION], ["assistant", ANSWER], ["user", QUESTION]]), {}, {})) {
    // a hit, shown as text
  }
  for await (const _ of await agent.llmNode(ctx([["user", "how do I reset my password"]]), {}, {})) {
    // the next caller turn
  }
  assert.ok(session.transcript.some((t) => t.content === ANSWER && t.role === "assistant"));
});

test("a cached answer with an emoji is still matched by its spoken words", { skip }, async () => {
  const text = "Refunds take five business days \u{1F44D}";
  const store = new Store({ [QUESTION]: text });
  const { agent, fakes } = make({ store });
  const key = JSON.stringify({ format: "pcm16-16000", language: "und", speed: "1", text, voice: "v" });
  store.tool.set(key, Buffer.from(PCM.buffer).toString("base64"));
  for await (const _ of await agent.llmNode(ctx([["user", QUESTION]]), {}, {})) {
    // a hit with audio
  }
  async function* transformed() {
    yield "Refunds take five business days"; // LiveKit's emoji filter ran
  }
  const frames = await readAll(await agent.ttsNode(transformed(), {}));
  assert.ok(frames.length > 0);
  assert.deepStrictEqual(fakes.ttsCalls, []); // played from the cache
});

test("an answer cut off while spoken stays in the call's transcript, never shared", { skip }, async () => {
  const { agent, store, session } = make();
  const pieces = await readAll(await agent.llmNode(ctx([["user", QUESTION]]), {}, {}));
  async function* text() {
    for (const p of pieces) yield p;
  }
  const reader = (await agent.ttsNode(text(), {})).getReader();
  await reader.read();
  await reader.cancel(); // the caller cut in
  assert.deepStrictEqual(store.writes, []);
  assert.strictEqual(session.transcript.at(-1).content, ANSWER);
});
