"use strict";

// Server-free tests for RealtimeAdapter and RealtimeGate.
//
// No network, no websocket: a fake client stands in for CrowkisClient so the
// speech-to-speech turn gate is verified in isolation — what it injects, what
// it suppresses, and above all that it never suppresses the respond event on a
// miss. Run:  node test-realtime.js

const assert = require("node:assert");
const { test } = require("node:test");
const { Agent } = require("./agent.js");
const { VoiceSession } = require("./voice.js");
const { RealtimeAdapter, RealtimeGate } = require("./realtime.js");

const TRANSCRIPT_EVENT = "provider.transcript.done";
const INJECT_EVENT = "provider.item.add";
const RESPOND_EVENT = "provider.respond.now";

class FakeClient {
  constructor(confidence = 0.99) {
    this.confidence = confidence;
    this.shared = new Map();
    this.reads = [];
    this.writes = [];
    this.tools = new Map();
  }

  async cgetHit(query) {
    this.reads.push(query);
    const response = this.shared.get(query);
    if (response === undefined) return null;
    const body = Buffer.from(String(response));
    return {
      response: body,
      similarity: 0.99,
      ttlRemaining: 600,
      matchedKey: Buffer.from("k"),
      confidence: this.confidence,
      hitType: "semantic",
    };
  }

  async cset(query, response) {
    this.writes.push(query);
    this.shared.set(query, response);
  }

  async ctoolget(tool, key) {
    const found = this.tools.get(`${tool} ${key}`);
    return found === undefined ? null : found;
  }

  async ctoolset(tool, key, result) {
    this.tools.set(`${tool} ${key}`, result);
  }

  async close() {}
}

class ExplodingSession {
  constructor() {
    this.calls = 0;
  }

  async decide() {
    this.calls += 1;
    throw new Error("the cache connection dropped mid-call");
  }
}

function adapter(transcriptField = "transcript") {
  return new RealtimeAdapter({
    transcriptEvent: TRANSCRIPT_EVENT,
    transcriptField,
    injectEvent: INJECT_EVENT,
    respondEvent: RESPOND_EVENT,
  });
}

function session(client, options = {}) {
  return new VoiceSession(new Agent("voice-gate", { client }), {
    voice: "v1",
    ...options,
  });
}

function transcriptEvent(text, field = "transcript") {
  return { type: TRANSCRIPT_EVENT, [field]: text };
}

function types(events) {
  return events.map((event) => event.type);
}

// --- adapter validation -----------------------------------------------------

test("every event name is refused when blank or not a string", () => {
  const good = {
    transcriptEvent: TRANSCRIPT_EVENT,
    transcriptField: "transcript",
    injectEvent: INJECT_EVENT,
    respondEvent: RESPOND_EVENT,
    roleField: "role",
    textField: "text",
  };
  let refusals = 0;
  for (const name of Object.keys(good)) {
    for (const bad of ["", "   ", null, 7, [], {}]) {
      const args = { ...good, [name]: bad };
      assert.throws(
        () => new RealtimeAdapter(args),
        (error) => error instanceof Error && error.message.includes(name),
        `${name}=${JSON.stringify(bad)} was accepted: the gate would never fire`
      );
      refusals += 1;
    }
  }
  assert.strictEqual(refusals, 36);
  assert.throws(() => new RealtimeAdapter(), Error);
  assert.throws(() => new RealtimeAdapter({}), Error);
});

test("a dotted path with an empty segment is refused", () => {
  for (const bad of ["a..b", ".transcript", "transcript.", "."]) {
    assert.throws(() => adapter(bad), Error, `${bad} was accepted as a path`);
  }
  // negative half: the shapes that look similar but are whole still build.
  assert.deepStrictEqual(adapter("a.b").transcriptPath, ["a", "b"]);
  assert.deepStrictEqual(adapter("transcript").transcriptPath, ["transcript"]);
});

test("the same arguments that fail blank succeed when named", () => {
  const built = adapter();
  assert.strictEqual(built.transcriptEvent, TRANSCRIPT_EVENT);
  assert.strictEqual(built.respond().type, RESPOND_EVENT);
  assert.strictEqual(built.inject("user", "hi")[built.roleField], "user");
  assert.strictEqual(built.inject("user", "hi")[built.textField], "hi");
  assert.notStrictEqual(built.respond().type, INJECT_EVENT);
});

test("the gate refuses anything that is not an adapter or a session", () => {
  const client = new FakeClient();
  assert.throws(() => new RealtimeGate(session(client), {}), TypeError);
  assert.throws(() => new RealtimeGate(session(client), null), TypeError);
  assert.throws(() => new RealtimeGate({}, adapter()), TypeError);
  assert.throws(() => new RealtimeGate(null, adapter()), TypeError);
  // negative half: the correct pair is accepted.
  assert.ok(new RealtimeGate(session(client), adapter()) instanceof RealtimeGate);
});

// --- routing ----------------------------------------------------------------

test("an unrelated event returns nothing and never asks the cache", async () => {
  const client = new FakeClient();
  const gate = new RealtimeGate(session(client), adapter());

  assert.deepStrictEqual(await gate.handle({ type: "provider.audio.delta" }), []);
  assert.deepStrictEqual(client.reads, []);
  assert.strictEqual(gate.stats().transcripts, 0);

  client.shared.set("what does the pro plan cost", "It is forty dollars a month.");
  await gate.handle(transcriptEvent("what does the pro plan cost"));
  assert.deepStrictEqual(client.reads, ["what does the pro plan cost"]);
  assert.strictEqual(gate.stats().transcripts, 1);
});

test("a hit injects two turns and sends no respond event", async () => {
  const client = new FakeClient();
  client.shared.set("what does the pro plan cost", "It is forty dollars a month.");
  const gate = new RealtimeGate(session(client), adapter());

  const out = await gate.handle(transcriptEvent("what does the pro plan cost"));

  assert.deepStrictEqual(types(out), [INJECT_EVENT, INJECT_EVENT]);
  assert.ok(!types(out).includes(RESPOND_EVENT), "a hit still asked the model to answer");
  assert.deepStrictEqual(out.map((e) => e.role), ["user", "assistant"]);
  assert.strictEqual(gate.stats().served, 1);
  assert.strictEqual(gate.stats().suppressed, 1);
  assert.strictEqual(gate.stats().forwarded, 0);
});

test("a miss sends exactly one respond event and injects nothing", async () => {
  const client = new FakeClient();
  const gate = new RealtimeGate(session(client), adapter());

  const out = await gate.handle(transcriptEvent("what does the pro plan cost"));

  assert.deepStrictEqual(types(out), [RESPOND_EVENT]);
  assert.ok(!types(out).includes(INJECT_EVENT), "a miss injected an answer nobody has");
  assert.strictEqual(gate.stats().served, 0);
  assert.strictEqual(gate.stats().suppressed, 0);
  assert.strictEqual(gate.stats().forwarded, 1);
});

test("an unconfident hit is forwarded not served", async () => {
  const client = new FakeClient(0.1);
  client.shared.set("what does the pro plan cost", "It is forty dollars a month.");
  const gate = new RealtimeGate(session(client), adapter());

  assert.deepStrictEqual(
    types(await gate.handle(transcriptEvent("what does the pro plan cost"))),
    [RESPOND_EVENT]
  );

  client.confidence = 0.99;
  assert.deepStrictEqual(
    types(await gate.handle(transcriptEvent("what does the pro plan cost"))),
    [INJECT_EVENT, INJECT_EVENT]
  );
});

test("an empty transcript is forwarded rather than matched", async () => {
  const client = new FakeClient();
  client.shared.set("", "never spoken");
  const gate = new RealtimeGate(session(client), adapter());

  for (const blank of ["", "   ", "\n\t"]) {
    assert.deepStrictEqual(types(await gate.handle(transcriptEvent(blank))), [
      RESPOND_EVENT,
    ]);
  }
  assert.deepStrictEqual(client.reads, []);
  assert.strictEqual(gate.stats().forwarded, 3);
  assert.strictEqual(gate.stats().suppressed, 0);
});

// --- nested transcripts -----------------------------------------------------

test("a dotted field resolves a nested transcript", async () => {
  const client = new FakeClient();
  client.shared.set("where is my nearest branch", "Two streets over.");
  const built = adapter("content.input.transcript");
  const gate = new RealtimeGate(session(client), built);

  const event = {
    type: TRANSCRIPT_EVENT,
    content: { input: { transcript: "where is my nearest branch" } },
  };
  assert.strictEqual(built.transcriptOf(event), "where is my nearest branch");
  assert.deepStrictEqual(types(await gate.handle(event)), [INJECT_EVENT, INJECT_EVENT]);
});

test("the same text at the wrong depth is not found", async () => {
  const built = adapter("content.input.transcript");
  const flat = { type: TRANSCRIPT_EVENT, transcript: "where is my nearest branch" };
  assert.strictEqual(built.transcriptOf(flat), null);

  const client = new FakeClient();
  client.shared.set("where is my nearest branch", "Two streets over.");
  const gate = new RealtimeGate(session(client), built);
  assert.deepStrictEqual(types(await gate.handle(flat)), [RESPOND_EVENT]);
  assert.deepStrictEqual(client.reads, []);
});

test("an event keyed by name instead of type still matches", () => {
  const built = new RealtimeAdapter({
    transcriptEvent: "serverInput",
    transcriptField: "serverInput.transcription.text",
    injectEvent: INJECT_EVENT,
    respondEvent: RESPOND_EVENT,
  });
  const event = { serverInput: { transcription: { text: "do you ship overseas" } } };
  assert.strictEqual(built.transcriptOf(event), "do you ship overseas");
  assert.strictEqual(built.transcriptOf({ otherInput: { text: "hello" } }), null);
  assert.strictEqual(built.isTranscript(event), true);
  assert.strictEqual(built.isTranscript({ otherInput: {} }), false);
});

// --- spoken text ------------------------------------------------------------

test("the injected assistant text is exactly what was spoken", async () => {
  const spoken = "The pro plan is forty dollars a month.";
  const client = new FakeClient();
  client.shared.set("what does the pro plan cost", spoken);
  const gate = new RealtimeGate(session(client), adapter());

  const out = await gate.handle(transcriptEvent("what does the pro plan cost"));

  assert.strictEqual(out[0].text, "what does the pro plan cost");
  assert.strictEqual(out[1].text, spoken);
  assert.strictEqual(gate.pendingDecision.text, spoken);
  assert.strictEqual(out[1].text, gate.pendingDecision.text);
});

test("a different cached answer changes the injected text", async () => {
  const client = new FakeClient();
  client.shared.set("what does the pro plan cost", "Forty dollars.");
  const gate = new RealtimeGate(session(client), adapter());
  const first = await gate.handle(transcriptEvent("what does the pro plan cost"));

  client.shared.set("what does the pro plan cost", "Fifty dollars.");
  const second = await gate.handle(transcriptEvent("what does the pro plan cost"));

  assert.strictEqual(first[1].text, "Forty dollars.");
  assert.strictEqual(second[1].text, "Fifty dollars.");
  assert.notStrictEqual(first[1].text, second[1].text);
});

test("served audio is reachable and cleared on the next turn", async () => {
  const client = new FakeClient();
  client.shared.set("what does the pro plan cost", "Forty dollars.");
  const gate = new RealtimeGate(
    session(client, { synthesise: (text) => Buffer.from(text) }),
    adapter()
  );

  await gate.handle(transcriptEvent("what does the pro plan cost"));
  assert.deepStrictEqual(gate.pendingAudio, Buffer.from("Forty dollars."));

  await gate.handle(transcriptEvent("what is the weather like today"));
  assert.strictEqual(gate.pendingAudio, null);
  assert.strictEqual(gate.pendingDecision, null);
});

// --- malformed events -------------------------------------------------------

const SHAPES = [
  {},
  null,
  [],
  "a bare string",
  42,
  { type: null },
  { type: TRANSCRIPT_EVENT },
  { type: TRANSCRIPT_EVENT, transcript: null },
  { type: TRANSCRIPT_EVENT, transcript: 17 },
  { type: TRANSCRIPT_EVENT, transcript: ["nested", "nonsense"] },
  { type: TRANSCRIPT_EVENT, transcript: { deeply: { nested: {} } } },
  [{ type: TRANSCRIPT_EVENT, transcript: "in a list" }],
  { [TRANSCRIPT_EVENT]: null },
];

test("no shape ever raises and none of them is served", async () => {
  assert.ok(SHAPES.length >= 13, "too few malformed shapes to be worth trusting");
  const client = new FakeClient();
  const gate = new RealtimeGate(session(client), adapter());

  for (const shape of SHAPES) {
    const out = await gate.handle(shape);
    const kinds = types(out);
    assert.ok(
      kinds.length === 0 || (kinds.length === 1 && kinds[0] === RESPOND_EVENT),
      `${JSON.stringify(shape)} produced ${JSON.stringify(kinds)}`
    );
    assert.ok(!kinds.includes(INJECT_EVENT), "garbage was injected into the call");
  }

  assert.strictEqual(gate.stats().served, 0);
  assert.strictEqual(gate.stats().suppressed, 0);
  assert.strictEqual(gate.stats().events, SHAPES.length);
});

test("a nested dotted path survives the same garbage", async () => {
  const gate = new RealtimeGate(session(new FakeClient()), adapter("a.b.transcript"));
  const shapes = SHAPES.concat([
    { type: TRANSCRIPT_EVENT, a: null },
    { type: TRANSCRIPT_EVENT, a: { b: [] } },
    { type: TRANSCRIPT_EVENT, a: { b: { transcript: 1.5 } } },
  ]);
  for (const shape of shapes) {
    const kinds = types(await gate.handle(shape));
    assert.ok(
      kinds.length === 0 || (kinds.length === 1 && kinds[0] === RESPOND_EVENT),
      `${JSON.stringify(shape)} produced ${JSON.stringify(kinds)}`
    );
  }
  assert.strictEqual(gate.stats().suppressed, 0);
});

test("a session that raises forwards instead of killing the call", async () => {
  const broken = new ExplodingSession();
  const gate = new RealtimeGate(broken, adapter());

  const out = await gate.handle(transcriptEvent("what does the pro plan cost"));

  assert.deepStrictEqual(types(out), [RESPOND_EVENT]);
  assert.strictEqual(broken.calls, 1);
  assert.strictEqual(gate.stats().suppressed, 0);

  // negative half: a blank served text is refused the same way, not spoken.
  const blank = new RealtimeGate({ decide: async () => ({ action: "serve", text: "  " }) }, adapter());
  assert.deepStrictEqual(
    types(await blank.handle(transcriptEvent("what does the pro plan cost"))),
    [RESPOND_EVENT]
  );
  assert.strictEqual(blank.stats().suppressed, 0);
});

// --- suppression accounting -------------------------------------------------

test("suppressed counts exactly the avoided inferences", async () => {
  const client = new FakeClient();
  const cached = [
    "what does the pro plan cost",
    "what are your opening hours",
    "do you ship internationally",
  ];
  for (const question of cached) client.shared.set(question, `answer to ${question}`);
  const gate = new RealtimeGate(session(client), adapter());

  const script = cached.concat([
    "how much does a courier collection cost",
    "what does the pro plan cost",
    "when is the next public holiday",
    "what are your opening hours",
    { type: "provider.audio.delta" },
    "",
  ]);
  const expectedHits = 5;

  for (const turn of script) {
    await gate.handle(typeof turn === "string" ? transcriptEvent(turn) : turn);
  }

  const stats = gate.stats();
  assert.strictEqual(stats.suppressed, expectedHits);
  assert.strictEqual(stats.served, expectedHits);
  assert.strictEqual(stats.forwarded, 3);
  assert.strictEqual(stats.events, script.length);
  assert.strictEqual(stats.transcripts, script.length - 2);
  assert.notStrictEqual(stats.suppressed, stats.events);
});

test("nothing is suppressed when the cache is empty", async () => {
  const client = new FakeClient();
  const gate = new RealtimeGate(session(client), adapter());
  for (let i = 0; i < 5; i += 1) {
    await gate.handle(transcriptEvent("what does the pro plan cost"));
  }
  assert.strictEqual(gate.stats().suppressed, 0);
  assert.strictEqual(gate.stats().forwarded, 5);
});

// --- never suppress a miss --------------------------------------------------

test("every miss across twenty turns still gets a respond event", async () => {
  const client = new FakeClient();
  const known = {
    "what does the pro plan cost": "Forty dollars a month.",
    "what are your opening hours": "Nine until five, weekdays.",
    "do you ship internationally": "Yes, to most countries.",
    "how do i reset a password": "From the sign-in screen.",
  };
  for (const [question, answer] of Object.entries(known)) {
    client.shared.set(question, answer);
  }
  const gate = new RealtimeGate(session(client), adapter());

  const unknown = [
    "what is the courier collection cutoff",
    "when is the next public holiday",
    "do you have a student discount",
    "what is the warranty period",
    "can i change my delivery window",
    "where are your warehouses located",
  ];
  const names = Object.keys(known);
  const script = [];
  for (let index = 0; index < 20; index += 1) {
    if (index % 3 === 0) script.push(unknown[Math.floor(index / 3) % unknown.length]);
    else script.push(names[index % names.length]);
  }

  let misses = 0;
  let hits = 0;
  for (const said of script) {
    const out = await gate.handle(transcriptEvent(said));
    if (Object.prototype.hasOwnProperty.call(known, said)) {
      hits += 1;
      assert.deepStrictEqual(types(out), [INJECT_EVENT, INJECT_EVENT]);
    } else {
      misses += 1;
      assert.deepStrictEqual(
        types(out),
        [RESPOND_EVENT],
        `a miss on ${JSON.stringify(said)} produced no respond event: a silent dead call`
      );
    }
  }

  assert.strictEqual(script.length, 20);
  assert.ok(misses > 0, "the script was all hits, so it proved nothing about misses");
  assert.ok(hits > 0, "the script was all misses, so it proved nothing about hits");
  assert.strictEqual(gate.stats().forwarded, misses);
  assert.strictEqual(gate.stats().suppressed, hits);
});

test("a run of pure misses forwards every single turn", async () => {
  const client = new FakeClient();
  const gate = new RealtimeGate(session(client), adapter());
  for (let index = 0; index < 20; index += 1) {
    const out = await gate.handle(transcriptEvent(`an unseen question number ${index}`));
    assert.deepStrictEqual(types(out), [RESPOND_EVENT]);
  }
  assert.strictEqual(gate.stats().forwarded, 20);
  assert.strictEqual(gate.stats().suppressed, 0);
});
