"use strict";

// F8 step 5: the F3 review leftovers, each with a test that failed before its fix. The same cases as
// python/tests/test_f8_leftovers.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { voiceSession, _waitForWrites: waitForWrites } = require("../src/channels/voiceSession.js");
const { WordReading } = require("../src/understanding/slots.js");
const { ConformanceStore } = require("./conformance.js");

const FIRST = "what are your opening hours on sunday";
const READ_AS_FOLLOW_UP = "do you ship to canada";
const FOLLOW_UP = "how long does it take";

// A classifier that reads a stand-alone-looking turn as a follow-up (the word rules do not).
const readsOneTurnAsAFollowUp = {
  async classify(text) {
    const reading = new WordReading(text);
    return Object.create(reading, { isContextDependent: { value: text === READ_AS_FOLLOW_UP || reading.isContextDependent } });
  },
};

async function play(options) {
  const session = voiceSession({ client: new ConformanceStore(), agentId: "leftovers", ...options });
  let last = null;
  for (const said of [FIRST, READ_AS_FOLLOW_UP, FOLLOW_UP]) {
    last = await session.decide(said);
    if (last.needsModel) await session.record(last, "Sure, yes.");
  }
  return last.messages.map((m) => m.content);
}

test("a turn the classifier read as a follow-up does not root a later chain", async () => {
  assert.deepStrictEqual(await play({ classifier: readsOneTurnAsAFollowUp }), [FIRST, READ_AS_FOLLOW_UP, FOLLOW_UP]);
});

test("must still work: a stand-alone turn roots the chain", async () => {
  const session = voiceSession({ client: new ConformanceStore(), agentId: "leftovers" });
  let last = null;
  for (const said of [FIRST, FOLLOW_UP]) {
    last = await session.decide(said);
    if (last.needsModel) await session.record(last, "Sure, yes.");
  }
  assert.deepStrictEqual(last.messages.map((m) => m.content), [FIRST, FOLLOW_UP]);
});

// A recap of the call is never a template.
class TemplateStore extends ConformanceStore {
  constructor() {
    super();
    this.templates = [];
  }

  async cset(query, response, options = {}) {
    if (options.template) this.templates.push([query, response]);
    return super.cset(query, response, options);
  }
}

async function playTemplate(said, answer) {
  const store = new TemplateStore();
  const session = voiceSession({ client: store, agentId: "leftovers", values: { order_id: "A-1001", eta: "Tuesday" }, shareTemplates: true });
  await session.record(await session.decide(said), answer);
  await waitForWrites();
  return store.templates;
}

test("a recap of the call is never saved as a template", async () => {
  assert.deepStrictEqual(await playTemplate("What do you know about me?", "You are travelling to Lisbon with your sister. Order A-1001 arrives on Tuesday."), []);
});

test("must still work: an order status is still saved as a template", async () => {
  const templates = await playTemplate("Where is my order A-1001?", "Your order A-1001 arrives on Tuesday.");
  assert.strictEqual(templates.length, 1);
  assert.ok(!templates[0][1].includes("A-1001"));
});

// The first lookup of a fresh Agent: a server with a decision engine that has not judged the answer yet.
class EngineStore {
  constructor(engine) {
    this.engine = engine;
    this.tenant = null;
  }

  async cgetHit() {
    return { response: Buffer.from("Refunds take five days."), text: "Refunds take five days.", similarity: 0.97,
      ttlRemaining: 600, matchedKey: Buffer.from("k"), confidence: 0.99, hitType: "semantic" };
  }

  async cdecision() {
    return { engine: this.engine };
  }

  async ctoolget() {
    return null;
  }

  async close() {}
}

async function decideFresh(engine) {
  const session = voiceSession({ client: new EngineStore(engine), voice: "alloy" });
  const deadline = Date.now() + 2000;
  while (typeof session.agent._decides !== "boolean" && Date.now() < deadline) await new Promise((r) => setTimeout(r, 10)); // the factory asks off the call's path
  return session.decide("how much is the pro plan");
}

test("the first lookup of a fresh session holds a reworded unjudged hit", async () => {
  const held = await decideFresh(true);
  assert.strictEqual(held.action, "infer");
  assert.ok(held.reason.includes("not been judged"));
});

test("must still work: without an engine nothing is held", async () => {
  assert.strictEqual((await decideFresh(false)).action, "serve");
});
