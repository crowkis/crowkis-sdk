"use strict";
// Server 0.5.2 replies the client must handle: CSET NOTSTORED, CSCAN tenant and
// number cursors, the CMEMEXTRACT size and fact caps, AUTH on a server with no
// token, and CSET EX 0 being refused.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const { CrowkisClient, CrowkisError } = require("./index.js");
const { CrowkisMemory } = require("./memory.js");

const NOT_NAMED = "the answer holds personal details the question does not name, so it would never be served";

function stubbed(reply, options = {}) {
  const client = new CrowkisClient({ tenant: "acme", ...options });
  const sent = [];
  client.execute = async (...args) => {
    sent.push(args.map(String));
    return typeof reply === "function" ? reply(args) : reply;
  };
  client._hello3 = async () => {};
  return { client, sent };
}

async function warningsDuring(fn) {
  const seen = [];
  const onWarning = (w) => seen.push(w);
  process.on("warning", onWarning);
  try {
    await fn();
    await new Promise((r) => setImmediate(r));
  } finally {
    process.off("warning", onWarning);
  }
  return seen.filter((w) => w.name === "CrowkisWarning");
}

test("a NOTSTORED reply does not throw and warns once per reason", async () => {
  const other = `${NOT_NAMED} (second reason)`;
  const replies = [`NOTSTORED ${NOT_NAMED}`, `NOTSTORED ${NOT_NAMED}`, `NOTSTORED ${other}`];
  const { client } = stubbed(() => replies.shift());
  const warned = await warningsDuring(async () => {
    await client.cset("what is my balance", "your balance is 40");
    await client.cset("what is my balance", "your balance is 40");
    await client.cset("what is my balance", "your balance is 41");
  });
  assert.deepStrictEqual(warned.map((w) => w.message.includes("second reason")), [false, true]);
  assert.match(warned[0].message, /not cached/);
  assert.ok(!warned[0].message.includes("your balance"), "the answer leaked into a warning");
});

test("an OK reply warns nothing", async () => {
  const { client } = stubbed("OK");
  const warned = await warningsDuring(() => client.cset("q", "a"));
  assert.deepStrictEqual(warned, []);
});

test("getOrCompute, ask and cached still return the computed answer when it is not stored", async () => {
  const reason = `NOTSTORED ${NOT_NAMED} (helpers)`;
  const { client } = stubbed((args) => (args[0] === "CGET" ? null : reason));
  await warningsDuring(async () => {
    assert.strictEqual(await client.getOrCompute("q", async () => "computed"), "computed");
    assert.strictEqual(await client.ask("q", async () => "asked"), "asked");
    assert.strictEqual(await client.cached(async () => "wrapped")("q"), "wrapped");
  });
});

test("cscan sends the client's tenant, or the one passed", async () => {
  const { client, sent } = stubbed(["0", []]);
  await client.cscan();
  await client.cscan("7", { tenant: "other", count: 5 });
  assert.deepStrictEqual(sent, [
    ["CSCAN", "0", "TENANT", "acme"],
    ["CSCAN", "7", "COUNT", "5", "TENANT", "other"],
  ]);
});

test("cscan without any tenant sends none", async () => {
  const { client, sent } = stubbed(["0", []], { tenant: undefined });
  await client.cscan();
  assert.deepStrictEqual(sent, [["CSCAN", "0"]]);
});

test("a cscan loop follows number cursors and ends at 0", async () => {
  const pages = { 0: [Buffer.from("17"), [Buffer.from("a")]], 17: [Buffer.from("42"), []], 42: [Buffer.from("0"), [Buffer.from("b")]] };
  const { client } = stubbed((args) => pages[args[1]]);
  const keys = [];
  let cursor = "0";
  let pagesRead = 0;
  do {
    const page = await client.cscan(cursor);
    keys.push(...page.keys.map(String));
    cursor = page.cursor;
    pagesRead += 1;
  } while (cursor !== "0" && pagesRead < 10);
  assert.deepStrictEqual(keys, ["a", "b"]);
  assert.strictEqual(pagesRead, 3);
});

// The server's rule: refuse over 65,536 bytes, split clauses at . ! ? and new
// lines, refuse more than 64 facts. Each clause of three or more words is a fact.
function extractServer() {
  const calls = [];
  const reply = (args) => {
    const text = String(args[2]);
    calls.push(Buffer.byteLength(text));
    if (Buffer.byteLength(text) > 65536) throw new CrowkisError(`CMEMEXTRACT query is ${Buffer.byteLength(text)} bytes`);
    const facts = text.split(/[\n.!?]/).map((c) => c.trim()).filter((c) => c.split(/\s+/).length >= 3);
    if (facts.length > 64) throw new CrowkisError(`CMEMEXTRACT found ${facts.length} facts, over the 64`);
    return facts.map((f) => Buffer.from(f));
  };
  return { calls, reply };
}

test("a long conversation is sent in parts and every fact comes back in order", async () => {
  const server = extractServer();
  const { client, sent } = stubbed(server.reply);
  const sentences = Array.from({ length: 200 }, (_, i) => `I like item number ${i}.`);
  const facts = await client.cmemextract("bot", sentences.join(" "), { user: "u1", ex: 60 });
  assert.deepStrictEqual(facts.map(String), sentences.map((s) => s.slice(0, -1)));
  assert.ok(server.calls.length >= 5);
  for (const args of sent) {
    assert.deepStrictEqual([args[0], args[1], ...args.slice(3)], ["CMEMEXTRACT", "bot", "USER", "u1", "EX", "60", "TENANT", "acme"]);
  }
});

test("text over the byte cap, non-Latin and with no sentence end, is split under it", async () => {
  const server = extractServer();
  const { client } = stubbed(server.reply);
  const hindi = "मुझे चाय पसंद है और मैं दिल्ली में रहता हूँ ".repeat(3000);
  await client.cmemextract("bot", hindi);
  const unbroken = "x".repeat(150 * 1024);
  await client.cmemextract("bot", unbroken);
  assert.ok(server.calls.length >= 6);
  assert.ok(server.calls.every((bytes) => bytes < 60 * 1024), "a part reached the cap");
});

test("a chunk boundary never splits a multi-byte character", async () => {
  const parts = [];
  const { client } = stubbed((args) => { parts.push(args[2]); return []; });
  await client.cmemextract("bot", "🙂".repeat(40 * 1024));
  assert.strictEqual(parts.join(""), "🙂".repeat(40 * 1024));
  assert.ok(parts.every((p) => !p.includes("�")));
});

test("short text is sent once, as before, and the reply returned as is", async () => {
  const reply = [Buffer.from("I like tea")];
  const { client, sent } = stubbed(reply);
  assert.strictEqual(await client.cmemextract("bot", "I like tea. Hi.", { user: "u1" }), reply);
  assert.strictEqual(await client.cmemextract("bot", ""), reply);
  assert.deepStrictEqual(sent, [
    ["CMEMEXTRACT", "bot", "I like tea. Hi.", "USER", "u1", "TENANT", "acme"],
    ["CMEMEXTRACT", "bot", "", "TENANT", "acme"],
  ]);
});

test("CrowkisMemory.extract splits long text through the client", async () => {
  const server = extractServer();
  const { client } = stubbed(server.reply);
  const memory = new CrowkisMemory("bot", { user: "u1", client });
  const sentences = Array.from({ length: 100 }, (_, i) => `My favourite number is ${i}!`);
  const facts = await memory.extract(sentences.join("\n"));
  assert.strictEqual(facts.length, 100);
  assert.ok(server.calls.length >= 3);
});

test("CSET sends EX for a ttl, and none for 0, null or no ttl", async () => {
  const { client, sent } = stubbed("OK", { tenant: undefined });
  await client.cset("q", "a", { ttl: 60 });
  await client.cset("q", "a", { ttl: 0 });
  await client.cset("q", "a", { ttl: null });
  await client.cset("q", "a");
  assert.deepStrictEqual(sent, [["CSET", "q", "a", "EX", "60"], ["CSET", "q", "a"], ["CSET", "q", "a"], ["CSET", "q", "a"]]);
});

function authServer(reply) {
  return new Promise((resolve) => {
    const server = net.createServer((socket) => socket.on("data", () => socket.write(reply)));
    server.listen(0, "127.0.0.1", () => resolve(server));
  });
}

test("a token sent to a server with none fails with what to do", async (t) => {
  const server = await authServer(
    "-ERR AUTH <password> called without any password configured for the default user. Are you sure your configuration is correct?\r\n"
  );
  const client = new CrowkisClient({ port: server.address().port, authToken: "tok-secret-1", maxRetries: 0 });
  t.after(() => { client.close(); server.close(); });
  await assert.rejects(client.ping(), (error) => {
    assert.ok(error instanceof CrowkisError);
    assert.match(error.message, /the server has no CROWKIS_AUTH_TOKEN set; remove authToken or set the same token on the server/);
    assert.ok(!error.message.includes("tok-secret-1"));
    return true;
  });
});

test("a wrong token still fails with the server's own reply", async (t) => {
  const server = await authServer("-WRONGPASS invalid username-password pair\r\n");
  const client = new CrowkisClient({ port: server.address().port, authToken: "tok-secret-1", maxRetries: 0 });
  t.after(() => { client.close(); server.close(); });
  await assert.rejects(client.ping(), /WRONGPASS invalid username-password pair/);
});
