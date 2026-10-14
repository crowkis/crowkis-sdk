"use strict";
// Client robustness: a server error reply, a hung server and a logged client
// must never take down the process or leak the token.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const { CrowkisClient } = require("./index.js");

function serve(onData) {
  return new Promise((resolve) => {
    const server = net.createServer((socket) => socket.on("data", (chunk) => onData(socket, chunk)));
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

test("an error reply rejects the call instead of crashing the process", async () => {
  const server = await serve((socket) => socket.write("-ERR CSET rejected by security pipeline\r\n"));
  const client = new CrowkisClient({ port: server.address().port, maxRetries: 0 });
  let uncaught = null;
  const onUncaught = (e) => { uncaught = e; };
  process.on("uncaughtException", onUncaught);
  await assert.rejects(client.execute("CSET", "q", "a"), /rejected by security pipeline/);
  await new Promise((r) => setTimeout(r, 20));
  process.off("uncaughtException", onUncaught);
  assert.strictEqual(uncaught, null, "the error escaped as an uncaught exception");
  client.close();
  server.close();
});

test("a server that never answers times out instead of hanging the caller", async () => {
  const server = await serve(() => {});
  const client = new CrowkisClient({ port: server.address().port, timeoutMs: 150, maxRetries: 0 });
  const started = Date.now();
  await assert.rejects(client.execute("CGET", "q"), /timeout/);
  assert.ok(Date.now() - started < 1000, "the read was not bounded");
  client.close();
  server.close();
});

test("the auth token never appears when a client is logged", () => {
  const client = new CrowkisClient({ authToken: "secret-token-value" });
  assert.ok(!JSON.stringify(client).includes("secret-token-value"));
  assert.ok(!Object.keys(client).includes("authToken"));
  assert.strictEqual(client.authToken, "secret-token-value");
});

// Just enough RESP3 to script the replies below.
function resp(value) {
  if (value === null) return "_\r\n";
  if (typeof value === "boolean") return `#${value ? "t" : "f"}\r\n`;
  if (typeof value === "number") return `${Number.isInteger(value) ? ":" : ","}${value}\r\n`;
  if (typeof value === "string") return `$${Buffer.byteLength(value)}\r\n${value}\r\n`;
  if (Array.isArray(value)) return `*${value.length}\r\n${value.map(resp).join("")}`;
  const pairs = Object.entries(value);
  return `%${pairs.length}\r\n${pairs.map(([key, item]) => resp(key) + resp(item)).join("")}`;
}

// A client on a server that answers each command with the next reply and
// records what was sent. Both close when the test ends: a failed assertion
// must not leave the listener open and hang the run.
async function scripted(t, replies, options = {}) {
  const sent = [];
  const server = await serve((socket, chunk) => {
    sent.push(chunk.toString().split("\r\n").filter((_, index) => index > 0 && index % 2 === 0));
    socket.write(replies.shift());
  });
  const client = new CrowkisClient({ port: server.address().port, maxRetries: 0, ...options });
  t.after(() => {
    client.close();
    server.close();
  });
  return { client, sent };
}

test("a hit reports what the decision engine recorded, and defaults without one", async (t) => {
  const unjudged = { response: "a", similarity: 1, ttl: 5, key: "k", confidence: 0.9, hit_type: "exact" };
  const { client } = await scripted(t, [
    resp({}),
    resp(unjudged),
    resp({ ...unjudged, judged: true, lifetime: "slow", commitment: true, vouched: false }),
    resp({ ...unjudged, judged: 1, lifetime: "slow", commitment: 0, vouched: 1 }),
  ]);
  const flags = (hit) => [hit.judged, hit.lifetime, hit.commitment, hit.vouched];

  assert.deepStrictEqual(flags(await client.cgetHit("q")), [false, null, false, false]);
  assert.deepStrictEqual(flags(await client.cgetHit("q")), [true, "slow", true, false]);
  assert.deepStrictEqual(flags(await client.cgetHit("q")), [true, "slow", false, true]);
});

test("decision and notice commands are sent in order and answered in plain values", async (t) => {
  const replies = [
    resp({}),
    resp({ engine: true, lifetime: "slow", n: 2, all: ["x", { k: "v" }] }),
    resp({ id: "abc", removed: 2, preview: true }),
    resp([{ id: "abc", text: "we close at 3pm today", until: 1700000000 }]),
    resp(null),
    resp(1),
    resp(0),
    resp({ id: "def", removed: 0, preview: false }),
  ];
  const { client, sent } = await scripted(t, replies, { tenant: "acme" });

  assert.deepStrictEqual(await client.cdecision("what time do you close"), {
    engine: true,
    lifetime: "slow",
    n: 2,
    all: ["x", { k: "v" }],
  });
  assert.deepStrictEqual(
    await client.cnoticeAdd("we close at 3pm today", { lasts: 3600, preview: true }),
    { id: "abc", removed: 2, preview: true }
  );
  assert.deepStrictEqual(await client.cnoticeList(), [
    { id: "abc", text: "we close at 3pm today", until: 1700000000 },
  ]);
  assert.deepStrictEqual(await client.cnoticeList(), []);
  assert.strictEqual(await client.cnoticeClear("abc"), true);
  assert.strictEqual(await client.cnoticeClear("abc"), false);
  await client.cnoticeAdd("the pro plan is now 25", { tenant: "other" });

  assert.deepStrictEqual(sent, [
    ["HELLO", "3"],
    ["CDECISION", "what time do you close", "TENANT", "acme"],
    ["CNOTICE", "ADD", "we close at 3pm today", "EX", "3600", "PREVIEW", "TENANT", "acme"],
    ["CNOTICE", "LIST", "TENANT", "acme"],
    ["CNOTICE", "LIST", "TENANT", "acme"],
    ["CNOTICE", "CLEAR", "abc", "TENANT", "acme"],
    ["CNOTICE", "CLEAR", "abc", "TENANT", "acme"],
    ["CNOTICE", "ADD", "the pro plan is now 25", "TENANT", "other"],
  ]);
});

// ── B1: a reply type the client cannot read ───────────────────────────────

test("an unknown reply type rejects that call, and the next call works on a fresh connection", async (t) => {
  const { client, sent } = await scripted(t, ["?what\r\n", "*2\r\n:1\r\n?nested\r\n", "+PONG\r\n"], { timeoutMs: 1000 });
  let uncaught = null;
  const onUncaught = (e) => { uncaught = e; };
  process.on("uncaughtException", onUncaught);
  t.after(() => process.off("uncaughtException", onUncaught));

  await assert.rejects(client.execute("CGET", "q"), (e) => e.name === "CrowkisError" && /unexpected RESP frame: \?what/.test(e.message));
  await assert.rejects(client.execute("CGET", "q"), /unexpected RESP frame: \?nested/);
  assert.strictEqual(await client.ping(), true);
  await new Promise((r) => setTimeout(r, 20));
  assert.strictEqual(uncaught, null, "the bad frame escaped as an uncaught exception");
  assert.deepStrictEqual(sent, [["CGET", "q"], ["CGET", "q"], ["PING"]]);
});

test("after an unknown reply type the client reconnects: the next call runs on a new socket", async (t) => {
  let connections = 0;
  const replies = ["?what\r\n", "+PONG\r\n", "+PONG\r\n"];
  const server = net.createServer((socket) => {
    connections += 1;
    socket.on("data", () => socket.write(replies.shift()));
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const client = new CrowkisClient({ port: server.address().port, maxRetries: 0, timeoutMs: 1000 });
  t.after(() => { client.close(); server.close(); });
  await assert.rejects(client.execute("CGET", "q"), /unexpected RESP frame/);
  assert.strictEqual(await client.ping(), true);
  assert.strictEqual(await client.ping(), true);
  assert.strictEqual(connections, 2, "the poisoned socket was reused, or a socket was opened per call");
});

test("known reply types still parse on one connection (control)", async (t) => {
  const { client } = await scripted(t, [":7\r\n", "_\r\n", "#t\r\n", ",1.5\r\n", resp(["a", 2])]);
  assert.strictEqual(await client.execute("X"), 7);
  assert.strictEqual(await client.execute("X"), null);
  assert.strictEqual(await client.execute("X"), true);
  assert.strictEqual(await client.execute("X"), 1.5);
  assert.deepStrictEqual(plainOf(await client.execute("X")), ["a", 2]);
});

function plainOf(value) {
  if (Buffer.isBuffer(value)) return value.toString();
  if (Array.isArray(value)) return value.map(plainOf);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, plainOf(v)]));
  return value;
}

// ── B3: cmemforget without a query ─────────────────────────────────────────

test("cmemforget with a tenant and no query sends an empty query, not the word TENANT", async (t) => {
  const { client, sent } = await scripted(t, [resp({}), resp(3), resp(1), resp(0)]);
  assert.strictEqual(await client.cmemforget("bot", { tenant: "acme" }), 3);
  await client.cmemforget("bot", { query: "refund policy", user: "u1", threshold: 0.7, tenant: "acme" });
  await client.cmemforget("bot");
  assert.deepStrictEqual(sent, [
    ["HELLO", "3"],
    ["CMEMFORGET", "bot", "", "TENANT", "acme"],
    ["CMEMFORGET", "bot", "refund policy", "USER", "u1", "THRESHOLD", "0.7", "TENANT", "acme"],
    ["CMEMFORGET", "bot", ""],
  ]);
});

// ── B2: BUSY is retried like the Python client ─────────────────────────────

test("a BUSY reply is retried after its retry-after-ms hint", async (t) => {
  const { client, sent } = await scripted(t, ["-BUSY actor queue is at capacity; retry-after-ms 60\r\n", "+OK\r\n"], { maxRetries: 2 });
  const started = Date.now();
  assert.strictEqual(await client.execute("CSET", "q", "a"), "OK");
  assert.ok(Date.now() - started >= 55, "the retry did not wait for the hint");
  assert.deepStrictEqual(sent, [["CSET", "q", "a"], ["CSET", "q", "a"]]);
});

test("BUSY without a hint waits 50 ms; BUSY past maxRetries rejects with the server's text", async (t) => {
  const { client, sent } = await scripted(t, ["-BUSY try later\r\n", "-BUSY try later\r\n"], { maxRetries: 1 });
  const started = Date.now();
  await assert.rejects(client.execute("CGET", "q"), (e) => e.name === "CrowkisError" && e.message === "BUSY try later");
  assert.ok(Date.now() - started >= 45, "the default wait was skipped");
  assert.strictEqual(sent.length, 2);
});

test("a BUSY hint above 2 s is capped at 2 s", async (t) => {
  const { client } = await scripted(t, ["-BUSY retry-after-ms=999999\r\n", "+OK\r\n"], { maxRetries: 1 });
  const started = Date.now();
  assert.strictEqual(await client.execute("CGET", "q"), "OK");
  const waited = Date.now() - started;
  assert.ok(waited >= 1900 && waited < 3000, `waited ${waited} ms`);
});

test("an ordinary error reply and maxRetries 0 are still not retried (control)", async (t) => {
  const { client, sent } = await scripted(t, ["-ERR boom\r\n", "-BUSY retry-after-ms 1\r\n"], { maxRetries: 2 });
  await assert.rejects(client.execute("CSET", "q", "a"), /ERR boom/);
  client.maxRetries = 0;
  await assert.rejects(client.execute("CSET", "q", "a"), /^CrowkisError: BUSY/);
  assert.strictEqual(sent.length, 2);
});

// ── C1 / C2: CBUDGET RESET, STATS, SWEEP and the CPROMPT additions ─────────

test("cbudgetReset, stats and sweep send their exact frames and shape the replies", async (t) => {
  const budget = { tenant: "acme", status: "ok", used_pct: 0 };
  const engine = { memtable_bytes: 10, memtable_keys: 2, l0: 1 };
  const { client, sent } = await scripted(t, [
    resp({}), resp(budget), resp(budget), resp(budget), resp(engine), resp(null), resp(7), resp(null),
  ], { tenant: "acme" });
  assert.deepStrictEqual(plainOf(await client.cbudgetReset()), budget);
  await client.cbudgetReset("other");
  client.tenant = undefined;
  await client.cbudgetReset();
  assert.deepStrictEqual(await client.stats(), engine);
  assert.deepStrictEqual(await client.stats(), {});
  assert.strictEqual(await client.sweep(), 7);
  assert.strictEqual(await client.sweep(), 0);
  assert.deepStrictEqual(sent, [
    ["HELLO", "3"],
    ["CBUDGET", "RESET", "acme"],
    ["CBUDGET", "RESET", "other"],
    ["CBUDGET", "RESET", "default"],
    ["STATS"],
    ["STATS"],
    ["SWEEP"],
    ["SWEEP"],
  ]);
});

test("cprompt additions send their exact frames, minimal and with every option", async (t) => {
  const { client, sent } = await scripted(t, [
    resp(1), resp(0),
    resp(3), resp(4),
    resp("hi Ana"), resp(null), resp("x"),
    resp([2, "v2 text"]), resp(null), resp([1, "v1"]),
    "+OK\r\n", "+OK\r\n", "+OK\r\n",
  ], { tenant: "client-wide" });
  assert.strictEqual(await client.cpromptDel("greet"), true);
  assert.strictEqual(await client.cpromptDel("greet", { tenant: "acme" }), false);
  assert.strictEqual(await client.cpromptRollback("greet", 1), 3);
  assert.strictEqual(await client.cpromptRollback("greet", 2, { tenant: "acme" }), 4);
  assert.strictEqual((await client.cpromptRender("greet")).toString(), "hi Ana");
  assert.strictEqual(await client.cpromptRender("greet", { version: 2, tenant: "acme", vars: { name: "Ana", n: 1, q: "a=b c", "नाम": "अना" } }), null);
  await client.cpromptRender("greet", { version: 0, vars: {} });
  const pick = await client.cpromptAb("greet");
  assert.deepStrictEqual([pick.version, pick.template.toString()], [2, "v2 text"]);
  assert.strictEqual(await client.cpromptAb("greet", { subject: "user-9", tenant: "acme" }), null);
  await client.cpromptAb("greet", { subject: "TENANT" });
  assert.strictEqual(await client.cpromptAbset("greet", { 1: 70, 2: 30 }), true);
  assert.strictEqual(await client.cpromptAbset("greet", { 1: 100 }, { tenant: "acme" }), true);
  assert.strictEqual(await client.cpromptAbset("greet"), true);
  assert.deepStrictEqual(sent, [
    ["CPROMPT", "DEL", "greet"],
    ["CPROMPT", "DEL", "greet", "TENANT", "acme"],
    ["CPROMPT", "ROLLBACK", "greet", "1"],
    ["CPROMPT", "ROLLBACK", "greet", "2", "TENANT", "acme"],
    ["CPROMPT", "RENDER", "greet"],
    ["CPROMPT", "RENDER", "greet", "2", "TENANT", "acme", "VARS", "name=Ana", "n=1", "q=a=b c", "नाम=अना"],
    ["CPROMPT", "RENDER", "greet", "0"],
    ["CPROMPT", "AB", "greet"],
    ["CPROMPT", "AB", "greet", "TENANT", "acme", "SUBJECT", "user-9"],
    ["CPROMPT", "AB", "greet", "SUBJECT", "TENANT"],
    ["CPROMPT", "ABSET", "greet", "1", "70", "2", "30"],
    ["CPROMPT", "ABSET", "greet", "1", "100", "TENANT", "acme"],
    ["CPROMPT", "ABSET", "greet"],
  ]);
});

test("cprompt additions: null and error replies, and arguments the server would misread", async (t) => {
  const { client, sent } = await scripted(t, [
    resp(null), resp(null), "-ERR no such prompt 'nope'\r\n", "-ERR no version 9 for 'greet'\r\n",
    "-ERR A/B weights must be > 0\r\n", "-ERR CBUDGET RESET requires tenant\r\n",
  ]);
  assert.strictEqual(await client.cpromptDel("nope"), false);
  assert.strictEqual(await client.cpromptRollback("nope", 1), 0);
  await assert.rejects(client.cpromptRender("nope"), /no such prompt/);
  await assert.rejects(client.cpromptRollback("greet", 9), /no version 9/);
  await assert.rejects(client.cpromptAbset("greet", { 1: 0 }), /weights must be > 0/);
  await assert.rejects(client.execute("CBUDGET", "RESET"), /requires tenant/);
  // A bad argument is a plain Error, as Agent's argument checks throw (agent.js).
  const argError = (pattern) => (e) => e.constructor === Error && pattern.test(e.message);
  await assert.rejects(client.cpromptRender("greet", { vars: { "a=b": 1 } }), argError(/no "="/));
  await assert.rejects(client.cpromptRender("greet", { vars: { "": 1 } }), argError(/no "="/));
  await assert.rejects(client.cpromptAbset("greet", { 1: 0.5 }), argError(/whole numbers/));
  await assert.rejects(client.cpromptAbset("greet", { v1: 50 }), argError(/whole numbers/));
  await assert.rejects(client.cpromptAbset("greet", { 1: -5 }), argError(/whole numbers/));
  assert.strictEqual(sent.length, 6, "a rejected argument must not reach the server");
});

test("cprompt A/B: a Map of weights is sent, and weights stay in the server's range", async (t) => {
  const { client, sent } = await scripted(t, ["+OK\r\n", "+OK\r\n"]);
  assert.strictEqual(await client.cpromptAbset("greet", new Map([[1, 50], [2, 50]])), true);
  // The largest weight the server keeps (u32); one above it is refused here.
  assert.strictEqual(await client.cpromptAbset("greet", { 1: 4294967295 }), true);
  await assert.rejects(client.cpromptAbset("greet", { 1: 10, 2: 5000000000 }), /whole numbers/);
  assert.deepStrictEqual(sent, [
    ["CPROMPT", "ABSET", "greet", "1", "50", "2", "50"],
    ["CPROMPT", "ABSET", "greet", "1", "4294967295"],
  ]);
});
