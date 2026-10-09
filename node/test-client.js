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
