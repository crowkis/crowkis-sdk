"use strict";
// One server token (Crowkis 0.5.2): the admin client sends it as Bearer, `apiKey`
// still works as a deprecated alias, the RESP client accepts `token`, and the
// value never shows up in an error, a warning or a logged client.
const test = require("node:test");
const assert = require("node:assert");
const http = require("node:http");
const net = require("node:net");
const util = require("node:util");
const { CrowkisAdmin, CrowkisClient, CrowkisError } = require("./index.js");

const SECRET = "tok-7f3a-very-secret";

function httpServer(status = 200, body = '{"ok":true}') {
  const headers = [];
  const server = http.createServer((req, res) => {
    headers.push(req.headers);
    req.resume();
    req.on("end", () => {
      res.writeHead(status, { "content-type": "application/json" });
      res.end(body);
    });
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () =>
      resolve({ server, headers, url: `http://127.0.0.1:${server.address().port}` })));
}

test("the admin token goes out as Bearer", async () => {
  const { server, headers, url } = await httpServer();
  await new CrowkisAdmin({ baseUrl: url, token: SECRET }).flushTenant("acme");
  server.close();
  assert.strictEqual(headers[0].authorization, `Bearer ${SECRET}`);
  assert.strictEqual(headers[0]["x-crowkis-api-key"], undefined);
});

test("no token sends no Authorization header", async () => {
  const { server, headers, url } = await httpServer();
  await new CrowkisAdmin({ baseUrl: url }).health();
  server.close();
  assert.strictEqual(headers[0].authorization, undefined);
});

test("apiKey still sends X-Crowkis-Api-Key and warns once", async () => {
  const { server, headers, url } = await httpServer();
  const warned = [];
  const onWarning = (w) => warned.push(w);
  process.on("warning", onWarning);
  await new CrowkisAdmin({ baseUrl: url, apiKey: SECRET }).health();
  await new CrowkisAdmin({ baseUrl: url, apiKey: SECRET }).health();
  await new Promise((r) => setImmediate(r));
  process.off("warning", onWarning);
  server.close();
  assert.deepStrictEqual(headers.map((h) => h["x-crowkis-api-key"]), [SECRET, SECRET]);
  assert.deepStrictEqual(headers.map((h) => h.authorization), [undefined, undefined]);
  const deprecations = warned.filter((w) => w.name === "DeprecationWarning");
  assert.strictEqual(deprecations.length, 1);
  assert.match(deprecations[0].message, /token/);
  assert.ok(!deprecations[0].message.includes(SECRET));
});

test("token wins over apiKey", async () => {
  const { server, headers, url } = await httpServer();
  await new CrowkisAdmin({ baseUrl: url, token: SECRET, apiKey: "old" }).health();
  server.close();
  assert.strictEqual(headers[0].authorization, `Bearer ${SECRET}`);
  assert.strictEqual(headers[0]["x-crowkis-api-key"], undefined);
});

test("the token never appears in an error or a logged admin client", async () => {
  const { server, url } = await httpServer(401, '{"error":"missing or wrong token"}');
  const admin = new CrowkisAdmin({ baseUrl: url, token: SECRET });
  const legacy = new CrowkisAdmin({ baseUrl: url, apiKey: SECRET });
  const error = await admin.flushTenant("acme").then(() => null, (e) => e);
  server.close();
  assert.ok(error instanceof CrowkisError);
  assert.ok(!util.inspect(error).includes(SECRET));
  for (const client of [admin, legacy]) {
    assert.ok(!util.inspect(client).includes(SECRET));
    assert.ok(!JSON.stringify(client).includes(SECRET));
  }
  assert.strictEqual(admin.token, SECRET);
  assert.strictEqual(legacy.apiKey, SECRET);
});

test("a token with a line break is refused without echoing it", async () => {
  const admin = new CrowkisAdmin({ baseUrl: "http://127.0.0.1:1", token: `${SECRET}\r\nx-evil: 1` });
  const error = await admin.health().then(() => null, (e) => e);
  assert.ok(error instanceof CrowkisError);
  assert.ok(!util.inspect(error).includes(SECRET));
});

function respServer() {
  const received = [];
  const server = net.createServer((socket) =>
    socket.on("data", (chunk) => {
      received.push(chunk);
      socket.write("+OK\r\n".repeat((chunk.toString().match(/\*/g) || []).length));
    }));
  return new Promise((resolve) => server.listen(0, "127.0.0.1", () => resolve({ server, received })));
}

for (const [name, options, sendsAuth] of [
  ["token", { token: SECRET }, true],
  ["authToken", { authToken: SECRET }, true],
  ["auth_token", { auth_token: SECRET }, true],
  ["nothing", {}, false],
]) {
  test(`RESP client with ${name} ${sendsAuth ? "sends" : "does not send"} AUTH`, async () => {
    const { server, received } = await respServer();
    const client = new CrowkisClient({ port: server.address().port, maxRetries: 0, ...options });
    await client.execute("PING");
    client.close();
    server.close();
    const frames = Buffer.concat(received).toString();
    assert.strictEqual(frames.startsWith("*2\r\n$4\r\nAUTH\r\n"), sendsAuth);
    assert.strictEqual(frames.includes(SECRET), sendsAuth);
    assert.ok(!util.inspect(client).includes(SECRET));
  });
}
