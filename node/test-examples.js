"use strict";
// The custom voice loop example runs and does what it says (as python/tests/test_examples.py).
process.env.CROWKIS_SDK = __dirname + "/index.js";
const test = require("node:test");
const assert = require("node:assert");
const { Agent } = require("./agent.js");
const { VoiceSession } = require("./voice.js");
const loop = require("../examples/node_custom_voice_loop.js");

class Store {
  constructor() {
    this.shared = new Map();
    this.writes = [];
  }
  async cgetHit(q) {
    const found = this.shared.get(q);
    return found === undefined ? null : { response: Buffer.from(found), text: found, similarity: 0.99, ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }
  async cset(q, r) {
    this.writes.push([q, r]);
    this.shared.set(q, r);
  }
  async ctoolget() {
    return null;
  }
  async ctoolset() {}
  async close() {}
}

const session = (store) => new VoiceSession(new Agent("caller", { client: store }), { voice: "v" });

test("a miss, then a hit", async () => {
  const store = new Store();
  const said = await loop.main(session(store));
  assert.deepStrictEqual(said.map((s) => s.trim()), Array(2).fill("Refunds take five business days to reach your card."));
  assert.strictEqual(store.writes.length, 1);
});

test("a barge-in saves nothing", async () => {
  const store = new Store();
  const sent = [];
  async function* turns() {
    yield "what is your refund policy";
  }
  async function* llm() {
    for (const w of ["Refunds ", "take ", "five ", "days."]) yield w;
  }
  await loop.runCall(session(store), turns(), llm, async (t) => sent.push(t), async () => {}, () => sent.length >= 2);
  assert.strictEqual(sent.length, 2);
  assert.deepStrictEqual(store.writes, []);
});
