"use strict";
// Server settings from the environment (Crowkis 0.5.2), the same rule as Python:
// a value passed in code wins, then CROWKIS_HOST / CROWKIS_PORT / CROWKIS_AUTH_TOKEN
// (or CROWKIS_TOKEN) / CROWKIS_TENANT, then the parts of CROWKIS_URL, then the
// built-in default (127.0.0.1:6383, no token, no tenant). Every class that builds its
// own client follows it, and the token never shows up in a logged client or an error.
const test = require("node:test");
const assert = require("node:assert");
const net = require("node:net");
const util = require("node:util");
const { CrowkisClient } = require("./index.js");
const { Agent } = require("./agent.js");
const { CrowkisCache } = require("./langchain.js");
const { CrowkisMemory } = require("./memory.js");

const SECRET = "tok-env-9c2e-very-secret";
const NAMES = [
  "CROWKIS_HOST",
  "CROWKIS_PORT",
  "CROWKIS_AUTH_TOKEN",
  "CROWKIS_TOKEN",
  "CROWKIS_TENANT",
  "CROWKIS_URL",
];

// Runs fn with every CROWKIS_* variable cleared and `values` set, then restores them.
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

const settings = (c) => [c.host, c.port, c.authToken, c.tenant];

test("nothing set keeps today's defaults", () => {
  withEnv({}, () => {
    assert.deepStrictEqual(settings(new CrowkisClient()), ["127.0.0.1", 6383, undefined, undefined]);
  });
});

test("empty and blank variables count as not set", () => {
  withEnv(
    { CROWKIS_HOST: "", CROWKIS_PORT: "  ", CROWKIS_AUTH_TOKEN: "", CROWKIS_TENANT: " ", CROWKIS_URL: "" },
    () => {
      assert.deepStrictEqual(settings(new CrowkisClient()), ["127.0.0.1", 6383, undefined, undefined]);
    }
  );
});

test("each variable is used when nothing is passed", () => {
  withEnv(
    { CROWKIS_HOST: "10.0.0.5", CROWKIS_PORT: "6390", CROWKIS_AUTH_TOKEN: SECRET, CROWKIS_TENANT: "my-app" },
    () => {
      assert.deepStrictEqual(settings(new CrowkisClient()), ["10.0.0.5", 6390, SECRET, "my-app"]);
    }
  );
});

test("surrounding whitespace is ignored", () => {
  withEnv({ CROWKIS_HOST: " 10.0.0.5 ", CROWKIS_PORT: " 6390\n" }, () => {
    const c = new CrowkisClient();
    assert.deepStrictEqual([c.host, c.port], ["10.0.0.5", 6390]);
  });
});

test("CROWKIS_TOKEN is accepted and CROWKIS_AUTH_TOKEN wins over it", () => {
  withEnv({ CROWKIS_TOKEN: SECRET }, () => {
    assert.strictEqual(new CrowkisClient().authToken, SECRET);
  });
  withEnv({ CROWKIS_AUTH_TOKEN: SECRET, CROWKIS_TOKEN: "other" }, () => {
    assert.strictEqual(new CrowkisClient().authToken, SECRET);
  });
});

test("read when the client is created, not when the module loads", () => {
  const before = withEnv({}, () => new CrowkisClient());
  const after = withEnv({ CROWKIS_PORT: "6391" }, () => new CrowkisClient());
  assert.deepStrictEqual([before.port, after.port], [6383, 6391]);
});

const ENV = { CROWKIS_HOST: "10.0.0.5", CROWKIS_PORT: "6390", CROWKIS_AUTH_TOKEN: "from-env", CROWKIS_TENANT: "env-tenant" };

test("every value passed in code wins", () => {
  withEnv(ENV, () => {
    const c = new CrowkisClient({ host: "h", port: 7000, authToken: "from-code", tenant: "code-tenant" });
    assert.deepStrictEqual(settings(c), ["h", 7000, "from-code", "code-tenant"]);
  });
});

test("token and auth_token options win over the environment", () => {
  withEnv(ENV, () => {
    assert.strictEqual(new CrowkisClient({ token: "a" }).authToken, "a");
    assert.strictEqual(new CrowkisClient({ auth_token: "b" }).authToken, "b");
  });
});

test("a value in code only replaces that one setting", () => {
  withEnv(ENV, () => {
    assert.deepStrictEqual(settings(new CrowkisClient({ port: 7000 })), ["10.0.0.5", 7000, "from-env", "env-tenant"]);
  });
});

test("CROWKIS_URL: full, partial, IPv6, and the separate variables win over its parts", () => {
  withEnv({ CROWKIS_URL: `crowkis://:${SECRET}@10.0.0.5:6390/my-app` }, () => {
    assert.deepStrictEqual(settings(new CrowkisClient()), ["10.0.0.5", 6390, SECRET, "my-app"]);
  });
  withEnv({ CROWKIS_URL: "crowkis://10.0.0.5" }, () => {
    assert.deepStrictEqual(settings(new CrowkisClient()), ["10.0.0.5", 6383, undefined, undefined]);
  });
  withEnv({ CROWKIS_URL: "crowkis://[::1]:6390" }, () => {
    const c = new CrowkisClient();
    assert.deepStrictEqual([c.host, c.port], ["::1", 6390]);
  });
  withEnv(
    { CROWKIS_URL: `crowkis://:${SECRET}@10.0.0.5:6390/my-app`, CROWKIS_PORT: "6391", CROWKIS_TENANT: "other" },
    () => {
      assert.deepStrictEqual(settings(new CrowkisClient()), ["10.0.0.5", 6391, SECRET, "other"]);
    }
  );
  withEnv({ CROWKIS_URL: "crowkis://10.0.0.5:6390/my-app" }, () => {
    assert.deepStrictEqual(
      settings(new CrowkisClient({ host: "h", port: 7000, tenant: "t" })),
      ["h", 7000, undefined, "t"]
    );
  });
});

function assertNames(variable, values) {
  withEnv(values, () => {
    assert.throws(
      () => new CrowkisClient(),
      (err) => err.message.includes(variable) && !err.message.includes(SECRET)
    );
  });
}

test("bad values fail at once, name the variable and never echo the token", () => {
  assertNames("CROWKIS_PORT", { CROWKIS_PORT: "abc" });
  assertNames("CROWKIS_PORT", { CROWKIS_PORT: "0" });
  assertNames("CROWKIS_PORT", { CROWKIS_PORT: "70000" });
  assertNames("CROWKIS_PORT", { CROWKIS_PORT: "63.5" });
  assertNames("CROWKIS_URL", { CROWKIS_URL: `http://:${SECRET}@10.0.0.5:6390` });
  assertNames("CROWKIS_URL", { CROWKIS_URL: `crowkis://:${SECRET}@10.0.0.5:99999` });
  assertNames("CROWKIS_URL", { CROWKIS_URL: `crowkis://:${SECRET}@:6390` });
});

test("a port must be plain ASCII digits, and a URL port cannot be 0", () => {
  for (const text of ["6_383", "+80", "63.5", "٦٣٨٣"]) {
    assertNames("CROWKIS_PORT", { CROWKIS_PORT: text });
  }
  assertNames("CROWKIS_URL", { CROWKIS_URL: "crowkis://10.0.0.5:0" });
});

test("an unreadable URL carries the token nowhere", () => {
  for (const url of [`crowkis://default:${SECRET}`, `crowkis://[::1:${SECRET}`]) {
    withEnv({ CROWKIS_URL: url }, () => {
      let err;
      try {
        new CrowkisClient();
      } catch (e) {
        err = e;
      }
      assert.ok(err && err.message.includes("CROWKIS_URL"));
      assert.strictEqual(err.cause, undefined);
      assert.ok(!util.inspect(err).includes(SECRET));
      assert.ok(!String(err.stack).includes(SECRET));
    });
  }
});

test("with nothing set, explicit odd values behave as before", () => {
  withEnv({}, () => {
    const c = new CrowkisClient({ host: "", port: 0, token: "", tenant: "" });
    assert.deepStrictEqual(settings(c), ["127.0.0.1", 6383, undefined, ""]);
    const want = ["127.0.0.1", 6383, undefined, undefined];
    assert.deepStrictEqual(settings(new Agent("support").client), want);
    assert.deepStrictEqual(settings(new CrowkisCache().client), want);
    assert.deepStrictEqual(settings(new CrowkisMemory("support").client), want);
  });
});

test("an empty token or tenant in code counts as not passed", () => {
  withEnv({ CROWKIS_AUTH_TOKEN: SECRET, CROWKIS_TENANT: "env-tenant" }, () => {
    const c = new CrowkisClient({ token: "", tenant: "" });
    assert.deepStrictEqual([c.authToken, c.tenant], [SECRET, "env-tenant"]);
  });
});

test("CROWKIS_URL details: escapes, user-part token, uppercase scheme, query and fragment", () => {
  const resolve = (url) => withEnv({ CROWKIS_URL: url }, () => settings(new CrowkisClient()));
  assert.deepStrictEqual(resolve("crowkis://:a%20b%40c@h/t%2Fx"), ["h", 6383, "a b@c", "t/x"]);
  assert.deepStrictEqual(resolve("crowkis://only-token@h:6390"), ["h", 6390, "only-token", undefined]);
  assert.deepStrictEqual(resolve("CROWKIS://h:6390/my-app?x=1#y"), ["h", 6390, undefined, "my-app"]);
  // An escape that cannot be decoded is kept as written, as in Python, never thrown.
  assert.strictEqual(resolve("crowkis://:%zz@h")[2], "%zz");
  assert.strictEqual(resolve("crowkis://:%E0%A4%A@h")[2], "%E0%A4%A");
  assert.strictEqual(resolve("crowkis://:%E0%A4%A4x%FF@h")[2], "तx%FF");
});

test("a bad variable is ignored when code passes that value", () => {
  withEnv({ CROWKIS_PORT: "abc" }, () => {
    assert.strictEqual(new CrowkisClient({ port: 7000 }).port, 7000);
  });
});

test("the token from the environment is never printed", () => {
  withEnv({ CROWKIS_AUTH_TOKEN: SECRET }, () => {
    const c = new CrowkisClient();
    assert.ok(!util.inspect(c).includes(SECRET));
    assert.ok(!JSON.stringify(c).includes(SECRET));
  });
  withEnv({ CROWKIS_URL: `crowkis://:${SECRET}@10.0.0.5` }, () => {
    const c = new CrowkisClient();
    assert.ok(!util.inspect(c).includes(SECRET));
    assert.ok(!JSON.stringify(c).includes(SECRET));
  });
});

const WRAP_ENV = { CROWKIS_HOST: "10.0.0.5", CROWKIS_PORT: "6390", CROWKIS_AUTH_TOKEN: SECRET, CROWKIS_TENANT: "my-app" };

test("Agent, CrowkisCache and CrowkisMemory read the environment", () => {
  withEnv(WRAP_ENV, () => {
    const want = ["10.0.0.5", 6390, SECRET, "my-app"];
    assert.deepStrictEqual(settings(new Agent("support").client), want);
    assert.deepStrictEqual(settings(new CrowkisCache().client), want);
    assert.deepStrictEqual(settings(new CrowkisMemory("support").client), want);
  });
});

test("Agent, CrowkisCache and CrowkisMemory: code still wins", () => {
  withEnv(WRAP_ENV, () => {
    const opts = { host: "h", port: 7000, authToken: "c", tenant: "t" };
    const want = ["h", 7000, "c", "t"];
    assert.deepStrictEqual(settings(new Agent("support", opts).client), want);
    assert.deepStrictEqual(settings(new CrowkisCache(opts).client), want);
    assert.deepStrictEqual(settings(new CrowkisMemory("support", opts).client), want);
  });
});

// A one-shot RESP server that answers +OK to everything and records what it got.
function fakeServer() {
  const received = [];
  const server = net.createServer((socket) => {
    socket.on("data", (chunk) => {
      received.push(chunk);
      const frames = chunk.toString("latin1").split("*").length - 1;
      socket.write("+OK\r\n".repeat(frames));
    });
  });
  return new Promise((resolve) =>
    server.listen(0, "127.0.0.1", () =>
      resolve({ server, port: server.address().port, frames: () => Buffer.concat(received) })
    )
  );
}

test("over the wire: the token is sent as AUTH and an Agent puts the tenant on its commands", async () => {
  const { server, port, frames } = await fakeServer();
  const env = { CROWKIS_HOST: "127.0.0.1", CROWKIS_PORT: String(port), CROWKIS_AUTH_TOKEN: SECRET, CROWKIS_TENANT: "env-tenant" };
  const agent = withEnv(env, () => new Agent("support"));
  try {
    await agent.remember("prefers email");
  } finally {
    await agent.close();
    server.close();
  }
  const sent = frames();
  assert.ok(sent.toString("latin1").startsWith("*2\r\n$4\r\nAUTH\r\n"));
  assert.ok(sent.includes(SECRET));
  assert.ok(sent.includes("CMEMSET"));
  assert.ok(sent.includes("env-tenant"));
});
