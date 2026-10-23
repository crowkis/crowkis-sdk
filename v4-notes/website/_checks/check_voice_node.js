"use strict";
// Runs the Node voice pages' code against a real Crowkis server (CROWKIS_* in the
// environment), with a stand-in LLM and TTS. NODE_PATH must reach @crowkis/client (and
// @livekit/agents for the LiveKit check):  node check_voice_node.js core|livekit
const which = process.argv[2] || "core";
const results = [];
const check = (name, ok, detail = "") => { results.push(Boolean(ok)); console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? `  [${detail}]` : ""}`); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const syl = () => "bcdfghjklmnpqrstvwxz"[Math.floor(Math.random() * 20)] + "aeiou"[Math.floor(Math.random() * 5)];
const topic = "the " + [0, 1].map(() => Array.from({ length: 4 }, syl).join("")).join(" ") + " gadget";

// -- custom-loop-node.md: "The whole loop", as written --------------------------------------
const { voiceSession } = require("@crowkis/client");
const SYSTEM = "You are Acme's phone assistant. Be brief.";
const QUESTION = `how do I reset ${topic}`;
const llmCalls = [];
async function* myStreamingLlm(messages) {
  llmCalls.push(messages);
  for (const piece of ["Hold the button ", "for five seconds."]) yield piece;
}
async function* callerTurnsOf() { yield QUESTION; }
const spoken = [];
const tts = { send: async (piece) => { spoken.push(piece); } };
const play = async () => {};
const callerInterrupted = () => false;

async function runCall(callerTurns) {                  // your STT's final transcripts
  const session = voiceSession();                      // one per call
  try {
    for await (const said of callerTurns) {
      const stream = await session.respond(said, myStreamingLlm, { system: SYSTEM });
      if (stream.decision.audio) {                     // a cached answer with its audio
        await play(stream.decision.audio);             // no TTS
        continue;
      }
      for await (const piece of stream) {              // cached text, or the LLM's words as they arrive
        if (callerInterrupted()) {
          session.cancel();                            // stops the LLM; nothing is saved
          break;
        }
        await tts.send(piece);
      }
    }
    return session.stats();
  } finally {
    await session.agent.close();
  }
}

async function core() {
  const first = await runCall(callerTurnsOf());
  let second;
  for (let i = 0; i < 4; i += 1) {
    await sleep(2000);
    second = await runCall(callerTurnsOf());
    if (second.servedFromCache) break;
  }
  // A shared real server may already know a near-identical question from an earlier run.
  check("custom loop: the first caller's turn was answered", first.modelCalls + first.servedFromCache === 1, JSON.stringify(first).slice(0, 80));
  check("custom loop: a later caller is served from the cache", second.servedFromCache === 1, JSON.stringify(second).slice(0, 80));
  check("custom loop: the stats keys the page shows exist",
    ["turns", "servedFromCache", "modelCalls", "cacheHitPct", "cacheUnavailable", "missedLatencyBudget", "slowWrites", "audioUnavailable"].every((k) => k in second));
  check("custom loop: the caller heard the answer", spoken.join("").startsWith("Hold the button for five seconds."));
}

// -- livekit-node.md -----------------------------------------------------------------------
async function livekit() {
  const { voice, llm } = require("@livekit/agents");
  const { withCrowkis } = require("@crowkis/client/livekit");
  const question = `how do I charge ${topic}`;
  const counts = [];
  let stats;
  for (let i = 0; i < 5; i += 1) {
    let calls = 0;
    const own = new voice.Agent({ instructions: "You are Acme's phone assistant." });
    own.llmNode = async () => { calls += 1; return new ReadableStream({ start(c) { c.enqueue("Use the cable in the box."); c.close(); } }); };
    own.ttsNode = async (text) => { for await (const _ of text); return new ReadableStream({ start(c) { c.close(); } }); };
    Object.defineProperty(own, "tts", { get: () => ({ sampleRate: 16000, numChannels: 1, voice: "v" }) });
    const session = voiceSession();
    const agent = withCrowkis(own, { crowkis: session });           // as on the page
    const ctx = new llm.ChatContext([llm.ChatMessage.create({ role: "system", content: ["You are Acme's phone assistant."] }),
      llm.ChatMessage.create({ role: "user", content: [question] })]);
    const reader = (await agent.llmNode(ctx, {}, {})).getReader();
    const pieces = [];
    for (let r = await reader.read(); !r.done; r = await reader.read()) pieces.push(typeof r.value === "string" ? r.value : "");
    async function* text() { for (const p of pieces) yield p; }
    const out = (await agent.ttsNode(text(), {})).getReader();
    while (!(await out.read()).done);
    stats = agent.crowkis.stats();                                   // the page's check
    counts.push(calls);
    await session.agent.close();
    if (counts.length > 1 && calls === 0) break;
    await sleep(2000);
  }
  check("livekit: the first call was answered", counts[0] === 0 || counts[0] === 1, JSON.stringify(counts));
  check("livekit: a later call is served from the cache", counts.at(-1) === 0, JSON.stringify(counts));
  check("livekit: session.stats() has servedFromCache", "servedFromCache" in stats);
}

({ core, livekit })[which]()
  .then(() => { console.log(`${results.filter(Boolean).length}/${results.length} passed`); process.exit(results.every(Boolean) ? 0 : 1); })
  .catch((e) => { console.error(e); process.exit(2); });
