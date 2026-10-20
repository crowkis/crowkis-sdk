"use strict";

// SEGMENT (what besides the question changes the answer: reply language, region,
// knowledge version) is sent exactly when it is set, so every existing call sends the
// same frame as before. Mirrors python/tests/test_segment.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { CrowkisClient } = require("./index.js");
const { Agent } = require("./agent.js");

const SEGMENT = "kb=3;lang=hi;region=in;channel=chat";

function scripted() {
  const client = new CrowkisClient({ tenant: "acme" });
  const sent = [];
  client.execute = async (...args) => {
    sent.push(args.map(String));
    return null;
  };
  client._hello3 = async () => {};
  return { client, sent };
}

test("cset, cget, cgetHit and cstale send it when set", async () => {
  const { client, sent } = scripted();
  await client.cset("q", "a", { segment: SEGMENT });
  await client.cget("q", { segment: SEGMENT });
  await client.cgetHit("q", { segment: SEGMENT });
  await client.cstale("q", undefined, SEGMENT);
  assert.deepStrictEqual(sent, [
    ["CSET", "q", "a", "TENANT", "acme", "SEGMENT", SEGMENT],
    ["CGET", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
    ["CGET", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
    ["CSTALE", "q", "TENANT", "acme", "SEGMENT", SEGMENT],
  ]);
});

test("frames are unchanged without it", async () => {
  const { client, sent } = scripted();
  await client.cset("q", "a");
  await client.cget("q");
  await client.cgetHit("q");
  await client.cstale("q");
  for (const frame of sent) assert.ok(!frame.includes("SEGMENT"), frame.join(" "));
});

test("the agent passes it only when set", async () => {
  const { client, sent } = scripted();
  const agent = new Agent("bot", { client });
  await agent.ask("q", { segment: SEGMENT });
  await agent.learn("q", "a", { segment: SEGMENT });
  await agent.ask("q");
  await agent.learn("q", "a");
  assert.deepStrictEqual(sent.slice(0, 2).map((f) => f.slice(-2)), [["SEGMENT", SEGMENT], ["SEGMENT", SEGMENT]]);
  assert.ok(sent.slice(2).every((f) => !f.includes("SEGMENT")));
});
