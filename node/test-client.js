"use strict";
// Client robustness: a server error reply, a hung server and a logged client
// must never take down the process or leak the token.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const { CrowkisClient } = require("./index.js");

function serve(onData) {
  return new Promise((resolve) => {
    const server = net.createServer((socket) => socket.on("data", () => onData(socket)));
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
