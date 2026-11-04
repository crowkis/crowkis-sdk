"use strict";
// Failure matrix: every server failure x every core entry point, against a real TCP socket
// (the twin of python/tests/test_failure_matrix.py).
//
// A tiny RESP stand-in on 127.0.0.1 is told to hang, answer slowly, refuse CSET or refuse AUTH
// (and a closed port is "down"), so the client's real socket code runs. Each cell asserts: no
// exception reaches the call; a defined outcome (the model answered, the save is "not stored"
// with a reason); the specific counter that failure must move; and that nothing logged (console,
// process warnings) carries the caller's question or the answer.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const voiceInternals = require("./src/channels/voiceSession.js");
const { voiceSession } = voiceInternals;
const { Chat } = require("./src/channels/chat.js");
const { CallSession } = require("./src/channels/callSession.js");
const { RealtimeAdapter, RealtimeGate } = require("./src/channels/realtime.js");
const { Agent } = require("./src/client/agent.js");
const { CrowkisClient } = require("./index.js");
const { TurnFrame } = require("./src/understanding/model/frame.js");

const QUESTION = "how do wyvern eggs hatch under a gloomy moonlit sky";
const ANSWER = "Wyvern eggs hatch only when the quartzmoss ember is kept warm.";
const PIECES = ["Wyvern eggs hatch only when ", "the quartzmoss ember is kept warm."];
const TOKEN = "matrix-token";
const DELAY_MS = 250; // the "slow" row: after the latency budget, before the timeout
const SETTLE_MS = 4000;
const QUOTES_QUESTION = "cset_error_quotes_question";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// A RESP server that misses every CGET and says OK to everything else, until told otherwise.
async function standIn(mode) {
  const sockets = new Set();
  const server = net.createServer((socket) => {
    sockets.add(socket);
    socket.on("error", () => {});
    let buffer = Buffer.alloc(0);
    socket.on("data", (chunk) => {
      buffer = Buffer.concat([buffer, chunk]);
      for (let command = take(buffer); command; command = take(buffer)) {
        buffer = buffer.subarray(command.used);
        reply(socket, command.args);
      }
    });
  });
  function reply(socket, args) {
    const name = args[0].toString().toUpperCase();
    if (mode === "hang") return; // accepted, never answered
    if (name === "AUTH") return socket.write(mode === "wrong_token" ? "-WRONGPASS invalid username-password pair\r\n" : "+OK\r\n");
    if (name === "HELLO") return socket.write("+OK\r\n");
    const send = () => {
      if (name === "CSET" && mode === "cset_refused") return socket.write("-ERR CSET rejected by security pipeline\r\n");
      // A server whose error quotes the query it refused.
      if (name === "CSET" && mode === "cset_echo") return socket.write(`-ERR cannot store ${args[1]}\r\n`);
      return socket.write(name === "CSET" ? "+OK\r\n" : "$-1\r\n");
    };
    if (mode === "slow") setTimeout(() => !socket.destroyed && send(), DELAY_MS);
    else send();
  }
  if (mode !== "down") await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  else {
    await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
    const port = server.address().port;
    await new Promise((resolve) => server.close(resolve)); // the port is now closed
    return { port, close() {} };
  }
  return { port: server.address().port, close() { for (const s of sockets) s.destroy(); server.close(); } };
}

// One complete RESP array off the front of the buffer, or null.
function take(buffer) {
  const head = buffer.indexOf("\r\n");
  if (head < 0 || buffer[0] !== 42) return null;
  const count = Number(buffer.subarray(1, head));
  let at = head + 2;
  const args = [];
  for (let i = 0; i < count; i += 1) {
    const end = buffer.indexOf("\r\n", at);
    if (end < 0) return null;
    const size = Number(buffer.subarray(at + 1, end));
    if (buffer.length < end + 2 + size + 2) return null;
    args.push(buffer.subarray(end + 2, end + 2 + size));
    at = end + 2 + size + 2;
  }
  return { args, used: at };
}

// row -> server mode, lookup budget (ms), client timeout (ms), counters that must reach a value,
// counters that must stay 0. A closed port is "down"; on Windows a refused connect can take the
// connect timeout, so its budget is generous and the counter is the lookup error.
const ROWS = {
  down: ["down", 1000, 150, { cacheUnavailable: 1, failedWrites: 1 }, ["missedLatencyBudget", "slowWrites"]],
  hung: ["hang", 60, 300, { missedLatencyBudget: 1, slowWrites: 1 }, ["cacheUnavailable"]],
  slow: ["slow", 60, 1000, { missedLatencyBudget: 1, slowWrites: 1 }, ["failedWrites", "cacheUnavailable"]],
  cset_refused: ["cset_refused", 500, 500, { failedWrites: 1 }, ["missedLatencyBudget", "cacheUnavailable", "slowWrites"]],
  wrong_token: ["wrong_token", 500, 500, { cacheUnavailable: 1, failedWrites: 1 }, ["missedLatencyBudget", "slowWrites"]],
  [QUOTES_QUESTION]: ["cset_echo", 500, 500, { failedWrites: 1 }, ["missedLatencyBudget", "cacheUnavailable"]],
};

// Chat / CallSession keep their own counts (session.stats()).
const CHAT_COUNTS = {
  down: { lookup_errors: 1 },
  hung: { lookup_timeouts: 1 },
  slow: { lookup_timeouts: 1 },
  cset_refused: { save_refused: 1 },
  wrong_token: { lookup_errors: 1 },
  [QUOTES_QUESTION]: { save_refused: 1 },
};

// Node logs nothing for a refused write (the counter is the record), so the log checks are: no
// caller text in anything logged, even when the server's error quotes the question.
const ERROR_TYPES = ["CrowkisError", "TimeoutError", "ConnectionRefusedError", "ECONNREFUSED"];

const frameOf = { kind: "general", subject: "none", confidence: 0.9, question: QUESTION };
const oneFrame = { understand: () => TurnFrame.fromDict(frameOf) };
const llm = async () => ANSWER;
const messages = [{ role: "user", content: QUESTION }];

// Everything the SDK says: console output and process warnings.
function captureLogs() {
  const lines = [];
  const saved = {};
  for (const level of ["log", "info", "warn", "error", "debug"]) {
    saved[level] = console[level];
    console[level] = (...args) => lines.push(args.map(String).join(" "));
  }
  const onWarning = (w) => lines.push(`${w.name}: ${w.message}`);
  process.on("warning", onWarning);
  return {
    lines,
    stop() {
      for (const level of Object.keys(saved)) console[level] = saved[level];
      process.off("warning", onWarning);
    },
  };
}

function assertNoCallerText(lines) {
  for (const line of lines) {
    assert.ok(!line.includes(QUESTION) && !line.includes(ANSWER), `caller text in a log: ${line}`);
    assert.ok(!/wyvern|quartzmoss/i.test(line), `caller text in a log: ${line}`);
  }
}

const namesAType = (lines) => lines.some((line) => ERROR_TYPES.some((name) => line.includes(name)));

async function settle(read, expect, zero = []) {
  const deadline = Date.now() + SETTLE_MS;
  const reached = () => Object.entries(expect).every(([name, value]) => (read()[name] || 0) >= value);
  while (!reached() && Date.now() < deadline) await sleep(20);
  const counts = read();
  for (const [name, value] of Object.entries(expect)) assert.strictEqual(counts[name] || 0, value, `${name}: want ${value}, stats ${JSON.stringify(counts)}`);
  for (const name of zero) assert.strictEqual(counts[name] || 0, 0, `${name} moved: ${JSON.stringify(counts)}`);
}

// Runs fn(server, logs) with the stand-in and log capture, then cleans up.
async function cell(row, fn) {
  const [mode] = ROWS[row];
  const server = await standIn(mode);
  const logs = captureLogs();
  try {
    await fn(server, logs.lines);
  } finally {
    logs.stop();
    server.close();
  }
}

function newSession(row, server) {
  const [, budget, timeout] = ROWS[row];
  return voiceSession({ host: "127.0.0.1", port: server.port, timeoutMs: timeout, latencyBudgetMs: budget, authToken: TOKEN });
}

function chatAgent(row, server) {
  const client = new CrowkisClient({ host: "127.0.0.1", port: server.port, timeoutMs: ROWS[row][2], maxRetries: 0, authToken: TOKEN });
  return new Agent("matrix", { client });
}

function assertNotStored(decision) {
  assert.strictEqual(decision.action, "infer");
  assert.strictEqual(decision.text, ANSWER);
  assert.strictEqual(decision.stored, false);
  assert.ok(typeof decision.notStored === "string" && decision.notStored, "no reason given");
}

async function checkVoiceCell(row, session, decision, lines) {
  const [, , , expect, zero] = ROWS[row];
  assertNotStored(decision);
  await settle(() => session.stats(), expect, zero);
  assertNoCallerText(lines);
}

for (const row of Object.keys(ROWS)) {
  test(`voice answer: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      const session = newSession(row, server);
      await checkVoiceCell(row, session, await session.answer(QUESTION, llm), lines);
    });
  });

  test(`voice decide then record: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      const session = newSession(row, server);
      const decision = await session.decide(QUESTION);
      assert.ok(decision.action === "infer" && decision.needsModel);
      await checkVoiceCell(row, session, await session.record(decision, ANSWER), lines);
    });
  });

  test(`voice respond stream: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      const session = newSession(row, server);
      const response = await session.respond(QUESTION, async function* () { yield* PIECES; });
      let said = "";
      for await (const piece of response) said += piece;
      assert.strictEqual(said, ANSWER);
      await checkVoiceCell(row, session, response.decision, lines);
    });
  });

  test(`chat turn: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      const chat = new Chat(chatAgent(row, server), oneFrame, { latencyBudgetMs: ROWS[row][1] });
      const reply = await chat.turn("t1", messages, llm);
      assert.ok(reply.text === ANSWER && reply.route === "shared" && !reply.fromCache, JSON.stringify(reply));
      assert.ok(!String(reply.outcome).startsWith("saved"), reply.outcome);
      assertNoCallerText(lines);
    });
  });

  test(`call session: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      const session = new CallSession(chatAgent(row, server), oneFrame, { latencyBudgetMs: ROWS[row][1] });
      const result = await session.handle(QUESTION);
      assert.ok(result.needsModel);
      const outcome = await session.recordAnswer(result, ANSWER);
      assert.ok(typeof outcome === "string" && !outcome.startsWith("saved"), outcome);
      await settle(() => session.stats(), CHAT_COUNTS[row]);
      assertNoCallerText(lines);
    });
  });
}

for (const row of ["down", "hung", "slow", "wrong_token"]) {
  test(`realtime gate: ${row}`, async () => {
    await cell(row, async (server, lines) => {
      // The gate only decides: on any failure the provider is asked to answer (a respond event).
      const session = newSession(row, server);
      const adapter = new RealtimeAdapter({ transcriptEvent: "t.done", transcriptField: "transcript", injectEvent: "item.add", respondEvent: "respond.now" });
      const gate = new RealtimeGate(session, adapter);
      const events = await gate.handle({ type: "t.done", transcript: QUESTION });
      assert.ok(events.length === 1 && events[0].type === "respond.now", JSON.stringify(events));
      assert.ok(gate.stats().forwarded === 1 && gate.stats().served === 0);
      const [, , , expect, zero] = ROWS[row];
      const lookup = ["cacheUnavailable", "missedLatencyBudget"];
      await settle(() => session.stats(), Object.fromEntries(Object.entries(expect).filter(([k]) => lookup.includes(k))), zero.filter((z) => lookup.includes(z)));
      assertNoCallerText(lines);
    });
  });
}

// A hung server with a token: the client has no timeout on the AUTH reply, so the lookup and the
// write never end (the python client fails them at its read timeout).
test("hung server with a token: the late write fails and is counted", async () => {
  await cell("hung", async (server, lines) => {
    const session = newSession("hung", server);
    await session.answer(QUESTION, llm);
    await settle(() => session.stats(), { failedWrites: 1 });
    assertNoCallerText(lines);
  });
});

// The handshake is bounded too: the AUTH reply is cut at timeoutMs, and the dead write leaves the pending set.
test("hung server with a token: the command fails at the client timeout and the pending writes drain", async () => {
  const server = await standIn("hang");
  try {
    const client = new CrowkisClient({ host: "127.0.0.1", port: server.port, timeoutMs: 300, maxRetries: 0, authToken: TOKEN });
    const started = Date.now();
    await assert.rejects(client.cget("q"), (error) => error.name === "CrowkisError");
    assert.ok(Date.now() - started < 3000);
    const session = newSession("hung", server);
    await session.answer(QUESTION, llm);
    await settle(() => session.stats(), { failedWrites: 1 });
    const deadline = Date.now() + SETTLE_MS;
    while (voiceInternals._pendingWrites.size && Date.now() < deadline) await sleep(20);
    assert.strictEqual(voiceInternals._pendingWrites.size, 0);
  } finally {
    server.close();
  }
});

// The same server without a token: the write is cut at the client timeout, counted and logged by type.
test("hung server without a token: the late write fails, is counted and logged by error type", async () => {
  const server = await standIn("hang");
  const logs = captureLogs();
  try {
    const session = voiceSession({ host: "127.0.0.1", port: server.port, timeoutMs: 300, latencyBudgetMs: 60 });
    const decision = await session.answer(QUESTION, llm);
    assert.strictEqual(decision.stored, false);
    await settle(() => session.stats(), { missedLatencyBudget: 1, slowWrites: 1, failedWrites: 1 }, ["cacheUnavailable"]);
    assertNoCallerText(logs.lines);
    assert.ok(namesAType(logs.lines), JSON.stringify(logs.lines));
  } finally {
    logs.stop();
    server.close();
  }
});

// -- LiveKit (Node): withCrowkis on real @livekit/agents types, as test-livekit.js drives it ----
let lk;
try {
  lk = require("@livekit/agents");
  var rtc = require("@livekit/rtc-node"); // eslint-disable-line no-var
} catch {
  lk = null;
}
const skipLiveKit = lk ? false : "@livekit/agents not installed";
const PCM = new Int16Array(640).fill(513);
const streamOf = (items) => new ReadableStream({ start(c) { for (const i of items) c.enqueue(i); c.close(); } });

async function readAll(stream) {
  const out = [];
  const reader = stream.getReader();
  for (let r = await reader.read(); !r.done; r = await reader.read()) out.push(r.value);
  return out;
}

for (const row of Object.keys(ROWS)) {
  test(`livekit js: ${row}`, { skip: skipLiveKit }, async () => {
    await cell(row, async (server, lines) => {
      const [, budget, timeout, expect, zero] = ROWS[row];
      const session = voiceSession({ host: "127.0.0.1", port: server.port, timeoutMs: timeout, latencyBudgetMs: budget, authToken: TOKEN, voice: "v" });
      const agent = new lk.voice.Agent({ instructions: "You are Acme's assistant." });
      agent.llmNode = async () => streamOf(PIECES);
      agent.ttsNode = async (text) => {
        for await (const piece of text) void piece;
        return streamOf([new rtc.AudioFrame(PCM, 16000, 1, PCM.length)]);
      };
      Object.defineProperty(agent, "tts", { get: () => ({ sampleRate: 16000, numChannels: 1, voice: "v" }) });
      const wrapped = require("./src/integrations/livekit.js").withCrowkis(agent, { crowkis: session });
      const chatCtx = new lk.llm.ChatContext([
        lk.llm.ChatMessage.create({ role: "system", content: ["You are Acme's assistant."] }),
        lk.llm.ChatMessage.create({ role: "user", content: [QUESTION] }),
      ]);
      const pieces = (await readAll(await wrapped.llmNode(chatCtx, {}, {}))).map((c) => (typeof c === "string" ? c : (c.delta && c.delta.content) || ""));
      async function* text() { yield* pieces; }
      await readAll(await wrapped.ttsNode(text(), {}));
      assert.strictEqual(pieces.join("").trim(), ANSWER);
      // BUG N1 (above) applies to the hung row's late write.
      const wanted = row === "hung" ? { missedLatencyBudget: 1, slowWrites: 1 } : expect;
      await settle(() => session.stats(), wanted, zero);
      assertNoCallerText(lines);
    });
  });
}
