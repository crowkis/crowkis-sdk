"use strict";
// Agent behaviour that only the retired e2e scripts used to check (T5, T6, T7, T10 in
// sdk-docs/open-items.md, 2026-10-21). Python twins: python/tests/test_agent_feature_gaps.py
// and the tool and speak tests in python/tests/test_agent_voice.py.
const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");

class ToolStore {
  constructor() { this.tools = new Map(); this.writes = 0; }
  async ctoolget(tool, key) { const v = this.tools.get(`${tool}|${key}`); return v === undefined ? null : v; }
  async ctoolset(tool, key, value) { this.tools.set(`${tool}|${key}`, value); this.writes += 1; }
}

// T5: Node agent.tool
test("a tool's result is cached per arguments", async () => {
  const agent = new Agent("bot", { client: new ToolStore() });
  const runs = [];
  const lookup = agent.tool(async function lookup(orderId) { runs.push(orderId); return { status: "shipped", id: orderId }; });
  const first = await lookup(7);
  const second = await lookup(7);
  assert.deepStrictEqual(runs, [7]);
  assert.deepStrictEqual(first, second);
  assert.deepStrictEqual(await lookup(8), { status: "shipped", id: 8 });
  assert.deepStrictEqual(runs, [7, 8]);
  assert.deepStrictEqual(agent.toolStats(), { calls: 3, cached: 1, executed: 2, avoidedPct: 33.33 });
});

test("a tool that throws caches nothing", async () => {
  const store = new ToolStore();
  const agent = new Agent("bot", { client: store });
  let explode = true;
  const runs = [];
  const flaky = agent.tool(async function flaky(x) { runs.push(x); if (explode) throw new Error("upstream down"); return { x }; });
  await assert.rejects(flaky(1), /upstream down/);
  assert.strictEqual(store.writes, 0);
  explode = false;
  assert.deepStrictEqual(await flaky(1), { x: 1 });
  assert.deepStrictEqual(runs, [1, 1], "it runs again: nothing was cached");
});

test("a tool needs a name", () => {
  const agent = new Agent("bot", { client: new ToolStore() });
  assert.throws(() => agent.tool(async () => 1), /named function/);
  assert.strictEqual(agent.tool(async () => 1, { name: "one" }).crowkisToolName, "one");
});

// T6: ask() validates its thresholds
test("ask refuses thresholds out of order or out of range, before any lookup", async () => {
  let lookups = 0;
  const agent = new Agent("bot", { client: { cgetHit: async () => { lookups += 1; return null; }, ctoolget: async () => null } });
  for (const bad of [{ serveAbove: 1.5 }, { cheapAbove: -0.1 }, { serveAbove: 0.5, cheapAbove: 0.7 }]) {
    await assert.rejects(agent.ask("what is the return policy", bad), /thresholds must satisfy/, JSON.stringify(bad));
  }
  assert.strictEqual(lookups, 0);
});

// T7: shared agent memory
class MemoryStore {
  constructor() { this.facts = new Map(); }
  async cmemset(agent, fact, { tenant } = {}) {
    const k = `${tenant}|${agent}`; this.facts.set(k, [...(this.facts.get(k) || []), fact]); return true;
  }
  async cmemget(agent, query, { tenant } = {}) {
    const words = new Set(query.toLowerCase().split(/\s+/));
    return (this.facts.get(`${tenant}|${agent}`) || []).filter((f) => f.toLowerCase().split(/\s+/).some((w) => words.has(w)));
  }
}

test("an agent reads what it remembered", async () => {
  const store = new MemoryStore();
  await new Agent("support", { client: store, tenant: "acme" }).remember("the customer prefers email");
  const rebuilt = new Agent("support", { client: store, tenant: "acme" }); // a new object, the same agent
  assert.deepStrictEqual(await rebuilt.recall("email"), ["the customer prefers email"]);
});

test("another agent reads it only when shared with", async () => {
  const store = new MemoryStore();
  await new Agent("billing", { client: store, tenant: "acme" }).remember("invoices go out on the 1st");
  assert.deepStrictEqual(await new Agent("support", { client: store, tenant: "acme" }).recall("invoices"), []);
  const sharing = new Agent("support", { client: store, tenant: "acme", sharesWith: ["billing", "  "] });
  assert.deepStrictEqual(await sharing.recall("invoices"), ["invoices go out on the 1st"]);
  assert.deepStrictEqual(await sharing.recall("invoices", { includeShared: false }), []);
});

test("must still work: another tenant never sees it", async () => {
  const store = new MemoryStore();
  await new Agent("support", { client: store, tenant: "acme" }).remember("the customer prefers email");
  assert.deepStrictEqual(await new Agent("support", { client: store, tenant: "orion", sharesWith: ["support"] }).recall("email"), []);
});

// T10: speak keeps one clip per voice and text
test("speak synthesises again for another voice or another text", async () => {
  const agent = new Agent("bot", { client: new ToolStore() });
  const made = [];
  const synth = async (text) => { made.push(text); return Buffer.from(`audio:${text}`); };
  const a = await agent.speak("Returns are free.", synth, { voice: "priya" });
  const again = await agent.speak("Returns are free.", synth, { voice: "priya" });
  assert.deepStrictEqual(again, a, "the same voice and text: the kept clip");
  await agent.speak("Returns are free.", synth, { voice: "arjun" });
  await agent.speak("Shipping is free.", synth, { voice: "priya" });
  assert.deepStrictEqual(made, ["Returns are free.", "Returns are free.", "Shipping is free."]);
});

test("speak refuses a blank voice", async () => {
  const agent = new Agent("bot", { client: new ToolStore() });
  await assert.rejects(agent.speak("Hi", async () => Buffer.from("x"), { voice: "" }), /voice/);
  await assert.rejects(agent.speak("Hi", async () => Buffer.from("x"), { voice: "   " }), /voice/);
});

// T9's two cases Node did not have: a filler inside a longer sentence, and the hit split.
const { voiceSession } = require("./voice.js");
const { ConformanceStore } = require("./conformance.js");
const voice = (options) => voiceSession({
  client: new ConformanceStore({ seed: { "what is the return policy": "Returns are free for 30 days." } }), ...options,
});

test("a filler trigger inside a longer sentence is not a filler", async () => {
  const session = voice({ fillers: { "one moment": "Sure, one moment." } });
  assert.notStrictEqual((await session.decide("one moment, what is the return policy")).action, "filler");
});

test("filler and cache hits are counted apart", async () => {
  const session = voice({ fillers: { hello: "Hi! How can I help?" } });
  await session.decide("hello");
  await session.decide("what is the return policy");
  const stats = session.stats();
  assert.deepStrictEqual([stats.fillerHitPct, stats.cacheHitPct], [50, 50]);
});
