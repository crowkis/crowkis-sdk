"use strict";
// Node packaging (Crowkis 0.5.2, Phase 1 step 8):
// - `import { VoiceSession, Agent, ... } from "@crowkis/client"` works under ESM, as the
//   README shows (the package's getters were invisible to Node's ESM loader), and gives
//   the same classes as require();
// - every subpath (`/voice`, `/agent`, `/langchain`, ...) has types, under TypeScript's
//   node16 resolution, and the types name what the code has;
// - two calls at once on a new client open one connection, not two (the second
//   connection was opened, overwrote the first, and the first was never closed);
// - an idle client no longer keeps the process alive: a script that forgets close()
//   still exits, and one with a request in flight still waits for it (the request's own
//   read timer would hold the process too; the socket is also re-ref'd while it runs);
// - close() while a connection is being made drops that connection.
const test = require("node:test");
const assert = require("node:assert");
const fs = require("node:fs");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { spawnSync, spawn } = require("node:child_process");
const { CrowkisClient } = require("./index.js");

const made = [];
process.on("exit", () => {
  for (const dir of made) {
    try {
      // The link to this folder goes first, on its own, so removing the project can
      // never reach through it into the SDK.
      fs.unlinkSync(path.join(dir, "node_modules", "@crowkis", "client"));
      fs.rmSync(dir, { recursive: true, force: true });
    } catch {
      // a temp folder left behind is harmless
    }
  }
});

// A project with @crowkis/client installed (a link to this folder), as a user has it.
function project() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "crowkis-pkg-"));
  made.push(dir);
  fs.mkdirSync(path.join(dir, "node_modules", "@crowkis"), { recursive: true });
  fs.symlinkSync(__dirname, path.join(dir, "node_modules", "@crowkis", "client"), "junction");
  return dir;
}

function run(dir, file, source) {
  fs.writeFileSync(path.join(dir, file), source);
  return spawnSync(process.execPath, [file], { cwd: dir, encoding: "utf8", timeout: 20000 });
}

test("ESM: every export of the package can be imported by name, and they are require()'s own", () => {
  const dir = project();
  const out = run(dir, "app.mjs", `
    import { createRequire } from "node:module";
    import * as ns from "@crowkis/client";
    import crowkis, { Crowkis, CrowkisClient, Agent, VoiceSession, voiceSession, TurnDecision,
      VoiceResponse, warmFromCalls, RealtimeAdapter, RealtimeGate, CrowkisError, CrowkisAdmin } from "@crowkis/client";
    import { VoiceSession as FromVoice } from "@crowkis/client/voice";
    import { Agent as FromAgent } from "@crowkis/client/agent";
    import { AudioClips } from "@crowkis/client/voiceTurns";
    import { CrowkisCache } from "@crowkis/client/langchain";
    import { CrowkisMemory } from "@crowkis/client/memory";
    const cjs = createRequire(import.meta.url)("@crowkis/client");
    const missing = Object.keys(cjs).filter((name) => !(name in ns));
    console.log(JSON.stringify({
      missing,
      same: VoiceSession === cjs.VoiceSession && FromVoice === VoiceSession && FromAgent === Agent
        && crowkis === cjs && Crowkis === CrowkisClient,
      kinds: [Agent, voiceSession, TurnDecision, VoiceResponse, warmFromCalls, RealtimeAdapter, RealtimeGate,
        CrowkisError, CrowkisAdmin, AudioClips, CrowkisCache, CrowkisMemory].map((x) => typeof x),
    }));
  `);
  assert.strictEqual(out.status, 0, out.stderr);
  const result = JSON.parse(out.stdout.trim().split("\n").pop());
  assert.deepStrictEqual(result.missing, []);
  assert.strictEqual(result.same, true);
  assert.ok(result.kinds.every((k) => k === "function"), JSON.stringify(result.kinds));
});

test("CommonJS keeps working as before", () => {
  const dir = project();
  const out = run(dir, "app.cjs", `
    const { VoiceSession, Agent, voiceSession } = require("@crowkis/client");
    const { VoiceSession: V } = require("@crowkis/client/voice");
    console.log(typeof VoiceSession, typeof Agent, typeof voiceSession, V === VoiceSession);
  `);
  assert.strictEqual(out.status, 0, out.stderr);
  assert.strictEqual(out.stdout.trim(), "function function function true");
});

test("types: every subpath is typed and the types match the code", (t) => {
  const dir = project();
  fs.writeFileSync(path.join(dir, "package.json"), JSON.stringify({ type: "module" }));
  fs.writeFileSync(path.join(dir, "tsconfig.json"), JSON.stringify({
    compilerOptions: { module: "node16", moduleResolution: "node16", strict: true, noEmit: true,
      skipLibCheck: true, target: "es2020", types: [] },
    files: ["app.ts"],
  }));
  fs.writeFileSync(path.join(dir, "app.ts"), `
    import { CrowkisClient, Agent, VoiceSession, voiceSession, TurnDecision, CrowkisGrpcClient, loadCrowkisGrpc } from "@crowkis/client";
    import { VoiceSession as V2, voiceSession as vs2, VoiceResponse, warmFromCalls,
      type VoiceSessionOptions, type VoiceSessionFactoryOptions, type TurnAction, type TurnDecisionOptions,
      type VoiceStats, type VoiceValues, type Commitments, type ModelCall, type StreamingModelCall,
      type ModelMessage, type TranscriptTurn, type PastTurn, type WarmStartTotals } from "@crowkis/client/voice";
    import { Agent as A2, waitForAudioStores, voiceAddonMissing, type AgentOptions, type AskOptions,
      type AskResult, type AudioStats, type RouteStats, type ToolStats, type CachedTool, type Synthesise } from "@crowkis/client/agent";
    import { CrowkisCache, type CrowkisCacheOptions } from "@crowkis/client/langchain";
    import { CrowkisMemory, type CrowkisMemoryOptions } from "@crowkis/client/memory";
    import { RealtimeGate, RealtimeAdapter, type RealtimeAdapterOptions, type RealtimeStats,
      type RealtimeTurnSource, type RealtimeClientEvent, type RealtimeInjectEvent,
      type RealtimeRespondEvent } from "@crowkis/client/realtime";
    import { AudioClips, AnswerPairing, TTS_TOOL, type AskedContext, type TurnGate, type AnswerReport } from "@crowkis/client/voiceTurns";
    // Every re-exported name resolves (a re-export of a name that does not exist fails here).
    type Named = [VoiceSessionOptions, VoiceSessionFactoryOptions, TurnAction, TurnDecisionOptions, VoiceStats,
      VoiceValues, Commitments, ModelCall, StreamingModelCall, ModelMessage, TranscriptTurn, PastTurn,
      WarmStartTotals, AgentOptions, AskOptions, AskResult, AudioStats, RouteStats, ToolStats,
      CachedTool<() => void>, Synthesise, CrowkisCacheOptions, CrowkisMemoryOptions, RealtimeAdapterOptions,
      RealtimeStats, RealtimeTurnSource, RealtimeClientEvent, RealtimeInjectEvent, RealtimeRespondEvent,
      TurnGate, AnswerReport];
    const values = [warmFromCalls, waitForAudioStores, voiceAddonMissing, RealtimeAdapter, CrowkisGrpcClient,
      loadCrowkisGrpc, TTS_TOOL] as const;

    const client = new CrowkisClient({ maxRetries: 0, backoffBaseMs: 10, timeoutMs: 1000 });
    const agent: A2 = new Agent("support", { client });
    const n: number = agent.audioErrors;
    const session: V2 = voiceSession({ voice: "v" });
    const s2: VoiceSession = vs2();
    const label: string = session.language + session.speed + session.audioFormat;
    const counts: number = session.lookupErrors + session.learnErrors + session.notShareable
      + session.heldCommitments + session.unspeakable + session.audioUnavailable;
    const flags: boolean = session.shortTurns && session.shareTemplates;
    const bps: number | undefined = session.bytesPerSecond;
    const unavailable: number = session.stats().audioUnavailable;
    async function go(d: TurnDecision, r: VoiceResponse) {
      d.text = "a fallback";
      await session.record(d, "x", { private: true });
      for await (const piece of r) { const p: string = piece; }
      const cache = new CrowkisCache({ ttl: 60, threshold: 0.9, client });
      const hit: { text: string }[] | null = await cache.lookup("q", "llm");
      await cache.update("q", "llm", [{ text: "a" }]);
      const memory = new CrowkisMemory("support", { user: "u", client });
      await memory.remember("fact", { ttl: 1 });
      await memory.recall("q", { k: 3 });
      const clips = new AudioClips(session, 16000);
      clips.ttsStarted(); clips.ttsText("hi"); clips.ttsAudio(new Uint8Array(2)); await clips.ttsStopped();
      const gate = { asked: [] as Array<AskedContext | null>, question: "", messages: [] as unknown[] };
      const pairing = new AnswerPairing(session, gate, clips, { onAnswer: async (info) => { const q: string = info.question; } });
      await pairing.responseStart(); pairing.responseText("hi");
      const todo = await pairing.responseEnd();
      if (todo) await pairing.record(...todo);
    }
    void [n, s2, label, counts, flags, bps, unavailable, go, RealtimeGate, values];
    export type { Named };
  `);
  const tsc = spawnSync("npx", ["-y", "-p", "typescript@5.6.3", "tsc", "-p", "."], {
    cwd: dir, encoding: "utf8", shell: true, timeout: 120000,
  });
  if (tsc.error || /not found|not recognized|ENOTFOUND|EAI_AGAIN|ENOTCACHED/i.test(tsc.stderr || "")) {
    t.skip(`TypeScript could not be run here: ${tsc.error || tsc.stderr}`);
    return;
  }
  assert.strictEqual(tsc.status, 0, tsc.stdout + tsc.stderr);
});

// A RESP server that counts connections and answers PING with +PONG.
function countingServer({ delayMs = 0 } = {}) {
  const sockets = [];
  const server = net.createServer((socket) => {
    sockets.push(socket);
    socket.on("data", (chunk) => {
      const frames = chunk.toString("latin1").split("*").length - 1;
      setTimeout(() => socket.write("+PONG\r\n".repeat(frames)), delayMs);
    });
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () => resolve({ server, sockets, port: server.address().port }))
  );
}

test("two calls at once on a new client open one connection", async () => {
  const { server, sockets, port } = await countingServer();
  const client = new CrowkisClient({ port, maxRetries: 0 });
  try {
    assert.deepStrictEqual(await Promise.all([client.ping(), client.ping(), client.ping()]), [true, true, true]);
    assert.strictEqual(sockets.length, 1);
  } finally {
    client.close();
    for (const s of sockets) s.destroy();
    server.close();
  }
});

function child(source, port) {
  return new Promise((resolve) => {
    const proc = spawn(process.execPath, ["-e", source], { env: { ...process.env, PORT: String(port) } });
    let out = "";
    proc.stdout.on("data", (d) => (out += d));
    const killer = setTimeout(() => proc.kill(), 5000);
    proc.on("exit", (code, signal) => {
      clearTimeout(killer);
      resolve({ code, signal, out: out.trim() });
    });
  });
}

const CLIENT = JSON.stringify(path.join(__dirname, "index.js"));

test("a script that forgets close() still exits", async () => {
  const { server, sockets, port } = await countingServer();
  try {
    const started = Date.now();
    const result = await child(`
      const { CrowkisClient } = require(${CLIENT});
      const client = new CrowkisClient({ port: Number(process.env.PORT) });
      client.ping().then((ok) => console.log("pong", ok));
    `, port);
    assert.strictEqual(result.signal, null, "the process had to be killed: the idle socket kept it alive");
    assert.strictEqual(result.out, "pong true");
    assert.ok(Date.now() - started < 4000);
  } finally {
    for (const s of sockets) s.destroy();
    server.close();
  }
});

test("a request in flight still keeps the process alive until it is answered", async () => {
  const { server, sockets, port } = await countingServer({ delayMs: 400 });
  try {
    const result = await child(`
      const { CrowkisClient } = require(${CLIENT});
      const client = new CrowkisClient({ port: Number(process.env.PORT) });
      (async () => {
        console.log("first", await client.ping());
        console.log("second", await client.ping());
      })();
    `, port);
    assert.strictEqual(result.signal, null);
    assert.strictEqual(result.out, "first true\nsecond true");
  } finally {
    for (const s of sockets) s.destroy();
    server.close();
  }
});

test("close() while a connection is being made drops that connection", async () => {
  let release;
  const gate = new Promise((r) => (release = r));
  const sockets = [];
  const server = net.createServer((socket) => sockets.push(socket));
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const client = new CrowkisClient({ port: server.address().port, maxRetries: 0 });
  try {
    const connecting = client.connect();
    client.close();
    await assert.rejects(connecting, /closed/);
    assert.strictEqual(client.socket, null);
    // A later call connects again as normal.
    const answering = new Promise((resolve) => server.once("connection", (s) => {
      s.on("data", () => s.write("+PONG\r\n"));
      resolve();
    }));
    const ping = client.ping();
    await answering;
    assert.strictEqual(await ping, true);
  } finally {
    release();
    await gate;
    client.close();
    for (const s of sockets) s.destroy();
    server.close();
  }
});
