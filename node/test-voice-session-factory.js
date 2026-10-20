"use strict";
// voiceSession(): a ready VoiceSession in one call, with live-call defaults (same as
// Python's crowkis.voice_session()). It builds the client and the Agent itself (server
// settings from the environment), with a 250 ms lookup budget, a 1 s server timeout and
// no retries. `voice` is optional: without it the session caches text only and never
// reads or stores audio. new VoiceSession(...) itself is unchanged.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const crowkis = require("./index.js");
const { CrowkisClient } = crowkis;
const { Agent } = require("./agent.js");
const { VoiceSession, voiceSession } = require("./voice.js");

const NAMES = ["CROWKIS_HOST", "CROWKIS_PORT", "CROWKIS_AUTH_TOKEN", "CROWKIS_TOKEN", "CROWKIS_TENANT", "CROWKIS_URL"];

function withEnv(values, fn) {
  const saved = {};
  for (const name of NAMES) {
    saved[name] = process.env[name];
    delete process.env[name];
  }
  Object.assign(process.env, values);
  try {
    return fn();
  } finally {
    for (const name of NAMES) {
      if (saved[name] === undefined) delete process.env[name];
      else process.env[name] = saved[name];
    }
  }
}

// A client that fails the test if anything is sent through it.
const untouchable = new Proxy(
  { tenant: undefined },
  {
    get(target, name) {
      if (name in target || name === "then") return target[name];
      throw new Error(`the server was asked: ${String(name)}`);
    },
  }
);

test("exported from the package and from the voice module", () => {
  assert.strictEqual(typeof voiceSession, "function");
  assert.strictEqual(crowkis.voiceSession, voiceSession);
});

test("one call gives a ready session with live-call defaults", () => {
  const session = withEnv({}, () => voiceSession());
  assert.ok(session instanceof VoiceSession);
  assert.strictEqual(session.latencyBudgetMs, 250);
  assert.strictEqual(session.agent.agentId, "voice");
  const client = session.agent.client;
  assert.deepStrictEqual([client.host, client.port], ["127.0.0.1", 6383]);
  assert.strictEqual(client.timeoutMs, 1000);
  assert.strictEqual(client.maxRetries, 0);
});

test("server settings come from the environment, and code wins", () => {
  const env = { CROWKIS_HOST: "10.0.0.5", CROWKIS_PORT: "6390", CROWKIS_AUTH_TOKEN: "tok", CROWKIS_TENANT: "my-app" };
  let s = withEnv(env, () => voiceSession());
  assert.deepStrictEqual(
    [s.agent.client.host, s.agent.client.port, s.agent.client.authToken, s.agent.client.tenant, s.agent.tenant],
    ["10.0.0.5", 6390, "tok", "my-app", "my-app"]
  );
  s = withEnv(env, () => voiceSession({ host: "h", port: 7000, authToken: "t", tenant: "code" }));
  assert.deepStrictEqual(
    [s.agent.client.host, s.agent.client.port, s.agent.client.authToken, s.agent.client.tenant, s.agent.tenant],
    ["h", 7000, "t", "code", "code"]
  );
  s = withEnv(env, () => voiceSession({ token: "t2" }));
  assert.strictEqual(s.agent.client.authToken, "t2");
});

test("defaults can be changed, and the budget turned off", () => {
  const s = withEnv({}, () => voiceSession({ agentId: "support", latencyBudgetMs: 400, timeoutMs: 2500 }));
  assert.deepStrictEqual([s.agent.agentId, s.latencyBudgetMs, s.agent.client.timeoutMs], ["support", 400, 2500]);
  assert.strictEqual(withEnv({}, () => voiceSession({ latencyBudgetMs: null })).latencyBudgetMs, null);
});

test("a timeout that is not positive is refused", () => {
  withEnv({}, () => {
    for (const bad of [0, -1]) assert.throws(() => voiceSession({ timeoutMs: bad }), /timeoutMs/);
  });
});

test("voice: null means text only, as None does in Python", () => {
  const s = withEnv({}, () => voiceSession({ voice: null }));
  assert.strictEqual(s._textOnly, true);
  assert.throws(() => voiceSession({ voice: null, synthesise: async () => Buffer.from("x") }), /voice/);
});

test("the factory accepts exactly the options VoiceSession declares", () => {
  // index.d.ts is the list users see: a constructor option added there but not to
  // the factory (or the other way round) fails here.
  const fs = require("node:fs");
  const dts = fs.readFileSync(require.resolve("./index.d.ts"), "utf8");
  const body = dts.slice(dts.indexOf("export interface VoiceSessionOptions {"));
  const declared = [...body.slice(0, body.indexOf("\n}")).matchAll(/^  (\w+)\??:/gm)].map((m) => m[1]);
  const { _SESSION_OPTIONS } = require("./voice.js");
  assert.deepStrictEqual(
    declared.filter((name) => !["voice", "latencyBudgetMs"].includes(name)).sort(),
    [..._SESSION_OPTIONS].sort()
  );
});

test("every other VoiceSession option is passed on", async () => {
  const s = withEnv({}, () =>
    voiceSession({
      serveAbove: 0.95,
      minWords: 4,
      ttl: 60,
      fillers: { hello: "Hi, how can I help?" },
      commitments: "never",
      language: "hi",
      speed: "1.1",
    })
  );
  assert.deepStrictEqual([s.serveAbove, s.minWords, s.ttl, s.commitments, s.language, s.speed], [0.95, 4, 60, "never", "hi", "1.1"]);
  assert.strictEqual((await s.decide("hello")).action, "filler");
});

test("an unknown option is an error, as in Python", () => {
  withEnv({}, () => {
    assert.throws(() => voiceSession({ serveAbov: 0.9 }), /serveAbov/);
  });
});

test("closing the agent closes the client it made, and not one passed in", async () => {
  const s = withEnv({}, () => voiceSession());
  let closed = 0;
  s.agent.client.close = async () => {
    closed += 1;
  };
  await s.agent.close();
  assert.strictEqual(closed, 1);

  const client = new CrowkisClient();
  let theirs = 0;
  client.close = async () => {
    theirs += 1;
  };
  await voiceSession({ client }).agent.close();
  assert.strictEqual(theirs, 0);
});

test("a client passed in is used as it is; server settings next to it are refused", () => {
  const client = new CrowkisClient({ host: "h", port: 7000, timeoutMs: 9000, maxRetries: 3, tenant: "t" });
  const s = voiceSession({ client });
  assert.strictEqual(s.agent.client, client);
  assert.deepStrictEqual([client.timeoutMs, client.maxRetries, s.agent.tenant], [9000, 3, "t"]);
  for (const extra of [{ host: "h" }, { port: 1 }, { authToken: "t" }, { token: "t" }, { tenant: "t" }, { timeoutMs: 2000 }]) {
    assert.throws(() => voiceSession({ client, ...extra }), /client/);
  }
});

test("voice: turns audio caching on; synthesise without it and a blank voice are refused", () => {
  withEnv({}, () => {
    const synth = async () => Buffer.from("pcm");
    const s = voiceSession({ voice: "eleven-rachel", synthesise: synth });
    assert.deepStrictEqual([s.voice, s.synthesise], ["eleven-rachel", synth]);
    assert.throws(() => voiceSession({ synthesise: synth }), /voice/);
    assert.throws(() => voiceSession({ voice: "" }));
    assert.throws(() => voiceSession({ voice: "   " }));
  });
  assert.throws(() => new VoiceSession(new Agent("support", { client: untouchable }), { voice: "" }));
});

test("text only: a synthesiser added later is used but never cached", async () => {
  const s = withEnv({}, () => voiceSession());
  s.agent.client = untouchable;
  assert.strictEqual(await s._voiced("Refunds take five days."), null);
  s.synthesise = async (text) => Buffer.from(`fresh:${text}`);
  s.agent.speak = async () => {
    throw new Error("cached");
  };
  assert.strictEqual(String(await s._voiced("Refunds take five days.")), "fresh:Refunds take five days.");
});

test("a stuck server costs a turn about a second, not ~15 s", async () => {
  const held = [];
  const server = net.createServer((socket) => held.push(socket)); // answer nothing
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const session = withEnv({ CROWKIS_PORT: String(server.address().port) }, () => voiceSession());
  const started = Date.now();
  let decision;
  try {
    decision = await session.answer(
      "how long do refunds usually take to arrive",
      async () => "Refunds arrive within five business days of approval."
    );
  } finally {
    await session.agent.close();
    for (const socket of held) socket.destroy();
    server.close();
  }
  const took = Date.now() - started;
  assert.ok(held.length > 0, "the turn never reached the server, so this proves nothing");
  assert.strictEqual(decision.text, "Refunds arrive within five business days of approval.");
  assert.strictEqual(decision.stored, false);
  // The save was tried; the turn stopped waiting for it at the latency budget (it gives
  // up in the background). Was: the turn waited the client's 1 s timeout.
  assert.strictEqual(session.slowWrites, 1, "the save was tried, and the turn did not wait for it");
  assert.ok(took < 1000, `took ${took} ms`);
});
