"use strict";

// Server-free tests for turn understanding v2.2 in Node: frame, call state, rule checker,
// understanding slot, CallSession and CallBridge. Mirrors the Python tests.
// Run: node --test test-call-session.js

const assert = require("node:assert");
const { test } = require("node:test");
const { TurnFrame } = require("./turn.js");
const { CallState } = require("./callstate.js");
const { RuleChecker, SHARED, TASK, URGENT, PERSONAL, TOOLS, AGENT } = require("./verify.js");
const { ReplayUnderstander, LLMUnderstander, WithFallback } = require("./understand.js");
const { CallSession, FILLER } = require("./session.js");
const { CallBridge, TTS_TOOL } = require("./callbridge.js");
const sdk = require("./index.js");

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const frame = (kw = {}) => TurnFrame.fromDict({ kind: "general", subject: "none", confidence: 0.9, question_type: "policy", entities: [], attributes: {}, ...kw });
const general = (question, kw = {}) => ({ kind: "general", subject: "none", confidence: 0.9, question, question_type: "policy", ...kw });
const check = (turn, kw = {}, state = new CallState(), checker = new RuleChecker()) => checker.check(frame(kw), turn, state);

class FakeClient {
  constructor({ slow = 0, broken = false } = {}) { this.tools = new Map(); this.slow = slow; this.broken = broken; }
  async ctoolget(tool, key) { if (this.broken) throw new Error("down"); await sleep(this.slow); return this.tools.get(tool + "|" + key) ?? null; }
  async ctoolset(tool, key, value) { this.tools.set(tool + "|" + key, value); }
}

class FakeAgent {
  constructor({ slow = 0, broken = false, client } = {}) { this.store = new Map(); this.saved = []; this.slow = slow; this.broken = broken; this.tenant = "t"; this.client = client || new FakeClient(); }
  async ask(key) {
    if (this.broken) throw new Error("cache down");
    await sleep(this.slow);
    return this.store.has(key) ? { route: "cache", answer: this.store.get(key), confidence: 0.99 } : { route: "expensive", answer: null, confidence: 0 };
  }
  async learn(key, answer, { ttl } = {}) { this.store.set(key, answer); this.saved.push([key, answer, ttl]); }
}

const scripted = (frames) => ({ understand: (turn) => TurnFrame.fromDict(frames[turn]) });

// --- frame and state --------------------------------------------------------------------

test("garbage model output is not shareable", () => {
  for (const raw of [null, {}, { kind: "banana" }, "nope"]) {
    const f = TurnFrame.fromDict(raw);
    assert.strictEqual(f.kind, "unclear");
    assert.strictEqual(f.confidence, 0);
  }
});

test("identifying comes from the entity type, not the model", () => {
  const f = frame({ entities: [{ text: "Sarah", type: "person_name", identifying: false }] });
  assert.deepStrictEqual(f.identifyingTexts, ["Sarah"]);
});

test("fillers never change the call state; tier lasts the whole call", () => {
  const s = new CallState();
  s.apply(frame({ question: "What are your hours?", attributes: { segment: { value: "premium", changes_answer: true } } }), { shared: true });
  const before = JSON.stringify(s.snapshot());
  for (let i = 0; i < 5; i++) s.apply(frame({ kind: "chitchat", question: "-" }), { shared: false });
  assert.strictEqual(JSON.stringify(s.snapshot()), before);
  assert.strictEqual(s.attributes.segment.value, "premium");
});

test("a greeting that names a place is remembered; names and IDs never are", () => {
  const s = new CallState();
  s.apply(frame({ kind: "chitchat", question: "-", entities: [{ text: "Park Winters", type: "place" }, { text: "Rahul", type: "person_name" }] }), { shared: false });
  assert.deepStrictEqual(s.facts, ["place: Park Winters"]);
  assert.ok(!JSON.stringify(s.snapshot()).includes("Rahul"));
});

test("an abstain clears the active question", () => {
  const s = new CallState({ activeQuestion: "What are your hours?" });
  s.apply(frame({ kind: "dialogue", abstain: true, question: "-" }), { shared: false });
  assert.strictEqual(s.activeQuestion, null);
});

// --- rule checker -----------------------------------------------------------------------

test("a name said with the question never reaches the key", () => {
  const v = check("What time is check-in? Sarah here.", { question: "What time is check-in?", entities: [{ text: "Sarah", type: "person_name" }] });
  assert.strictEqual(v.route, SHARED);
  assert.strictEqual(v.key, "[kb=1] What time is check-in?");
});

test("identifying details in the key block sharing; Saturday and prices do not", () => {
  for (const t of ["Where is order 55512?", "Can I change john@mail.com?"]) assert.ok(check(t, { question: t }).reasons.includes("V5_identifying"), t);
  assert.ok(check("What are your branch hours on Saturday?", { question: "What are your branch hours on Saturday?" }).shared);
  assert.ok(check("Is shipping free on orders over 10000 rupees?", { question: "Is shipping free on orders over 10000 rupees?" }).shared);
});

test("ungrounded words block; state, agent mentions and word forms ground", () => {
  assert.ok(!check("And for ten people?", { question: "What does the Max plan cost for 10 people?" }).shared);
  assert.ok(check("And for ten people?", { question: "What does the Pro plan cost for 10 people?" }, new CallState({ activeQuestion: "What does the Pro plan cost?" })).shared);
  const s = new CallState();
  s.noteAgentReply("That would be the Golden Gate Hotel.", ["Golden Gate Hotel"]);
  assert.ok(check("Where is that?", { question: "Where is the Golden Gate Hotel?", question_type: "place_fact" }, s).shared);
  assert.ok(check("I would like to know when promo code expires", { question: "When does a promo code expire?" }).shared);
});

test("routes: urgent, task, personal, tools, agent; own purchase contradicts general", () => {
  assert.strictEqual(check("I smell gas", { kind: "sensitive", subject: "self", urgent: true }).route, URGENT);
  assert.strictEqual(check("Under $100", { task_step: true, question: "x?" }).route, TASK);
  assert.strictEqual(check("Where is my order?", { kind: "personal", subject: "self" }).route, PERSONAL);
  assert.strictEqual(check("Cancel it.", { kind: "action", subject: "self" }).route, TOOLS);
  assert.strictEqual(check("Thanks!", { kind: "chitchat" }).route, AGENT);
  assert.ok(check("Can I return the shoes I bought?", { question: "Can I return shoes?", entities: [{ text: "the shoes I bought", type: "own_purchase" }] }).reasons.includes("V4_about_someone"));
});

test("answering the agent during a task is a task step; outside a task it is judged normally", () => {
  const s = new CallState();
  s.noteAgentReply("What is your budget?", [], "booking");
  assert.strictEqual(check("Under 100 dollars for two.", { question: "Which restaurants cost under 100 dollars for two?" }, s).route, TASK);
  const free = new CallState();
  free.noteAgentReply("What would you like to know?");
  assert.ok(check("Your return policy please.", { question: "What is your return policy?" }, free).shared);
});

test("key: tier only when it matters, location on place questions, expiry by type, knowledge version", () => {
  assert.ok(check("x premium shipping", { question: "How long does shipping take?", attributes: { segment: { value: "premium", changes_answer: true } } }, new CallState({ activeQuestion: "x premium shipping How long does shipping take" })).key.includes("segment=premium"));
  const s = new CallState();
  s.apply(frame({ kind: "dialogue", question: "-", attributes: { region: { value: "laguna beach" } }, entities: [{ text: "Laguna Beach", type: "place" }] }), { shared: false });
  s.noteAgentReply("I found The Press Bistro.", ["The Press Bistro"]);
  const v = check("Do they have steak there?", { question: "Does The Press Bistro have steak?", question_type: "place_fact" }, s);
  assert.ok(v.key.includes("region=laguna beach"));
  assert.strictEqual(v.ttl, 6 * 3600);
  const q = "What is your refund policy?";
  assert.notStrictEqual(check(q, { question: q }, new CallState(), new RuleChecker({ knowledgeVersion: "2" })).key, check(q, { question: q }).key);
});

// --- understanding slot ------------------------------------------------------------------

test("replay recognises exact repeats only, ignoring case and punctuation", () => {
  const r = new ReplayUnderstander();
  r.remember("Um, do you deliver on Sundays?", "Do you deliver on Sundays?", "policy");
  assert.strictEqual(r.understand("um do you deliver on sundays").question, "Do you deliver on Sundays?");
  assert.strictEqual(r.understand("do you deliver on sundays to Rahul").kind, "unclear");
});

test("LLM understander parses JSON, fails closed on garbage, never sends identity", async () => {
  let seen;
  const llm = new LLMUnderstander(async (m) => { seen = m; return "ok: " + JSON.stringify(general("What time is check-in?")); }, { business: "A hotel." });
  const s = new CallState();
  s.setIdentity("verified");
  assert.strictEqual((await llm.understand("What time is check-in?", s)).question, "What time is check-in?");
  assert.ok(seen[0].content.includes("A hotel."));
  assert.ok(!JSON.parse(seen[1].content).call_state.identity);
  assert.strictEqual((await new LLMUnderstander(async () => "no json").understand("x", s)).kind, "unclear");
});

test("a failing model falls back to replay", async () => {
  const u = new WithFallback(new LLMUnderstander(async () => { throw new Error("down"); }), new ReplayUnderstander({ "Do you price match?": "policy" }));
  assert.strictEqual((await u.understand("Do you price match?", new CallState())).question, "Do you price match?");
  assert.strictEqual(u.primaryFailures, 1);
});

// --- CallSession -------------------------------------------------------------------------

test("miss, save, then a hit for the next caller; the model never reads the name", async () => {
  const agent = new FakeAgent();
  const frames = { "Shipping time? Sarah here.": general("How long does shipping take?", { entities: [{ text: "Sarah", type: "person_name" }] }) };
  const first = new CallSession(agent, scripted(frames));
  const r = await first.handle("Shipping time? Sarah here.");
  assert.deepStrictEqual(r.messages, [{ role: "user", content: "How long does shipping take?" }]);
  assert.strictEqual(await first.recordAnswer(r, "Shipping takes 3 to 5 days."), "saved");
  const r2 = await new CallSession(agent, scripted(frames)).handle("Shipping time? Sarah here.");
  assert.ok(r2.servedFromCache);
});

test("urgent hook runs first and a broken hook does not end the call", async () => {
  const seen = [];
  const frames = { "I smell gas.": { kind: "sensitive", subject: "self", urgent: true } };
  assert.strictEqual((await new CallSession(new FakeAgent(), scripted(frames), { onUrgent: (t) => seen.push(t) }).handle("I smell gas.")).route, URGENT);
  assert.deepStrictEqual(seen, ["I smell gas."]);
  assert.strictEqual((await new CallSession(new FakeAgent(), scripted(frames), { onUrgent: () => { throw new Error("x"); } }).handle("I smell gas.")).route, URGENT);
});

test("fillers are local; slow or broken cache and model fall back, never block", async () => {
  assert.strictEqual((await new CallSession(new FakeAgent(), scripted({}), { fillers: { "thank you": "You're welcome." } }).handle("Thank you!")).route, FILLER);
  const frames = { "Do you price match?": general("Do you price match?") };
  const slow = new CallSession(new FakeAgent({ slow: 300 }), scripted(frames), { latencyBudgetMs: 30 });
  assert.ok((await slow.handle("Do you price match?")).needsModel);
  assert.strictEqual(slow.stats().lookup_timeouts, 1);
  const slowModel = { understand: async () => { await sleep(300); return TurnFrame.fromDict(general("Do you price match?")); } };
  const started = Date.now();
  const s = new CallSession(new FakeAgent(), slowModel, { understandBudgetMs: 30, replay: new ReplayUnderstander({ "Do you price match?": "policy" }) });
  assert.strictEqual((await s.handle("Do you price match?")).route, SHARED);
  assert.ok(Date.now() - started < 250);
  assert.strictEqual(s.stats().understand_timeouts, 1);
});

test("save check refuses non-answers, action claims, identifying details and tiers not in the key", async () => {
  const frames = { "How do I return an item?": general("How do I return an item?") };
  const answer = async (text, prep) => {
    const s = new CallSession(new FakeAgent(), scripted(frames));
    if (prep) prep(s);
    return s.recordAnswer(await s.handle("How do I return an item?"), text);
  };
  assert.strictEqual(await answer("Go to Orders and choose Return."), "saved");
  assert.strictEqual(await answer("Could you tell me which item?"), "refused:non_answer");
  assert.strictEqual(await answer("I've cancelled that for you."), "refused:action_claim");
  assert.strictEqual(await answer("Email returns@example.com about order 5551234."), "refused:identifying");
  assert.strictEqual(await answer("Premium members get 60 days.", (s) => s.state.apply(TurnFrame.fromDict({ kind: "personal", subject: "self", attributes: { segment: { value: "premium" } } }), { shared: false })), "refused:attribute_not_in_key");
});

test("barge-in and late turns are never saved", async () => {
  const agent = new FakeAgent();
  const A = "Do you price match?", B = "Do you ship to Canada?";
  const frames = { [A]: general(A), [B]: general(B) };
  const s = new CallSession(agent, scripted(frames));
  const r = await s.handle(A);
  assert.ok(s.cancel());
  assert.strictEqual(await s.recordAnswer(r, "Yes."), "cancelled");
  const old = await s.handle(A);
  const neu = await s.handle(B);
  assert.strictEqual(await s.recordAnswer(old, "Yes, we match prices."), "stale");
  assert.strictEqual(await s.recordAnswer(neu, "Yes, we ship to Canada."), "saved");
});

test("kill switch, replay-only mode and monitoring events without raw words", async () => {
  const frames = { "Price match? Sarah here.": general("Do you price match?", { entities: [{ text: "Sarah", type: "person_name" }] }) };
  const events = [];
  const s = new CallSession(new FakeAgent(), scripted(frames), { onEvent: (e) => events.push(e) });
  s.setMode("off");
  assert.strictEqual((await s.handle("Price match? Sarah here.")).route, AGENT);
  s.setMode("full");
  const r = await s.handle("Price match? Sarah here.");
  await s.recordAnswer(r, "Yes, we match prices.");
  assert.ok(!JSON.stringify(events).includes("Sarah"));
  assert.deepStrictEqual(events.slice(-2).map((e) => e.type), ["turn", "answer"]);
  const ro = new CallSession(new FakeAgent(), { understand: () => { throw new Error("must not be called"); } },
    { mode: "replay_only", replay: new ReplayUnderstander({ "Do you price match?": "policy" }) });
  assert.strictEqual((await ro.handle("Do you price match?")).route, SHARED);
  assert.throws(() => s.setMode("yolo"));
});

test("personal shapes phrase verified values only at the required identity, never for others", () => {
  const s = new CallSession(new FakeAgent(), scripted({}));
  s.registerShape("balance", "Your balance is {balance}.", { requires: "verified" });
  assert.strictEqual(s.phrase("balance", "₹2,400"), null);
  s.state.setIdentity("verified");
  assert.strictEqual(s.phrase("balance", "₹2,400"), "Your balance is ₹2,400.");
  assert.strictEqual(s.phrase("balance", "₹2,400", { subject: "other" }), null);
  assert.throws(() => s.registerShape("eta", "Soon."));
});

// --- CallBridge --------------------------------------------------------------------------

const SHIP = "How long does shipping take?";
const SYSTEM = { role: "system", content: "Be brief." };
const bridgeFor = (agent) => new CallBridge(new CallSession(agent, scripted({ [SHIP]: general(SHIP), "Where is my order?": { kind: "personal", subject: "self", confidence: 0.9 } })), { voice: "priya", sampleRate: 24000 });

test("bridge: a miss keeps system prompt and tools, drops the call history", async () => {
  const d = await bridgeFor(new FakeAgent()).onContext([SYSTEM, { role: "user", content: "I'm Rahul, order 55512." }, { role: "user", content: SHIP }], ["lookup_order"]);
  assert.deepStrictEqual(d.messages, [SYSTEM, { role: "user", content: SHIP }]);
  assert.deepStrictEqual(d.tools, ["lookup_order"]);
});

test("bridge: saved answer audio is stored whole and replayed; personal audio never", async () => {
  const agent = new FakeAgent();
  const b = bridgeFor(agent);
  await b.onContext([{ role: "user", content: SHIP }]);
  b.onTtsAudio(Buffer.from("AAAA"));
  assert.strictEqual(await b.onAnswer("Shipping takes 3 to 5 days."), "saved");
  b.onTtsAudio(Buffer.from("BBBB"));
  assert.ok(await b.onBotStopped());
  const d = await bridgeFor(agent).onContext([{ role: "user", content: SHIP }]);
  assert.strictEqual(d.action, "play_audio");
  assert.strictEqual(d.audio.toString(), "AAAABBBB");

  const p = new FakeAgent();
  const pb = bridgeFor(p);
  await pb.onContext([{ role: "user", content: "Where is my order?" }]);
  pb.onTtsAudio(Buffer.from("PERSONAL"));
  await pb.onAnswer("Your order arrives Tuesday.");
  assert.ok(!(await pb.onBotStopped()));
  assert.strictEqual(p.client.tools.size, 0);
});

test("bridge: interruption saves nothing; bad audio means synthesise", async () => {
  const agent = new FakeAgent();
  const b = bridgeFor(agent);
  await b.onContext([{ role: "user", content: SHIP }]);
  b.onInterruption();
  assert.strictEqual(await b.onAnswer("Shipping takes 3 to 5 days."), "not_recorded");
  assert.strictEqual(agent.store.size, 0);
  agent.store.set("[kb=1] " + SHIP, "Shipping takes 3 to 5 days.");
  agent.client.tools.set(TTS_TOOL + "|" + b._key("Shipping takes 3 to 5 days."), "not base64!!");
  assert.strictEqual((await bridgeFor(agent).onContext([{ role: "user", content: SHIP }])).action, "speak_text");
});

test("the new classes are exported from the package", () => {
  for (const name of ["CallSession", "CallState", "TurnFrame", "RuleChecker", "LLMUnderstander", "ReplayUnderstander", "WithFallback", "CallBridge"]) {
    assert.strictEqual(typeof sdk[name], "function", name);
  }
});
