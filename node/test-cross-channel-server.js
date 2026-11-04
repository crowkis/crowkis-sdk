"use strict";

// Chat and voice on a real server share nothing private (CROWKIS_CONFORMANCE_SERVER=1). The Node
// twin of python/tests/test_cross_channel_server.py: each run uses made-up words; one channel saves
// a general answer and a caller's private details, a fresh session of the other channel asks. Nothing
// it gets back, no write the SDK sent and no raw lookup may hold the details. A general answer stays
// inside its channel (the segment holds channel=): the same-channel controls prove it, the
// cross-channel cases assert it (v4 P5 item 5).
//
//   CROWKIS_CONFORMANCE_SERVER=1 CROWKIS_HOST=... CROWKIS_PORT=... CROWKIS_AUTH_TOKEN=... \
//     CROWKIS_TENANT=voice node --test test-cross-channel-server.js
const assert = require("node:assert");
const crypto = require("node:crypto");
const { test } = require("node:test");
const { Agent, Chat, CrowkisClient, LLMClassifier, LLMRewriter, voiceSession } = require("./index.js");
const { TurnFrame } = require("./src/understanding/model/frame.js");

const REAL = process.env.CROWKIS_CONFORMANCE_SERVER === "1";
const FINDABLE_MS = 10_000; // a new answer is findable on a real server within about a second
const SEPARATE_MS = 3_000; // waiting for something that must not happen: shorter
const SEGMENTS = [null, "kb=1;channel=voice", "kb=1;lang=und;channel=chat"];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// One run's made-up words: nothing already on the server can match them.
function words() {
  const h = crypto.randomBytes(4).toString("hex");
  // Letters only: a word with digits reads as an identifier and makes a question private.
  const u = [...h].map((c) => String.fromCharCode(97 + parseInt(c, 16))).join("");
  const w = {
    u,
    generalQ: `What are the opening hours of the zorblax${u} store?`,
    generalA: `The zorblax${u} store opens at 9 am.`,
    name: `Quillon Vrexbane${u}`,
    phone: "98" + String(parseInt(h, 16)).slice(0, 7).padEnd(7, "3"),
    order: `ZB${h.toUpperCase()}`,
  };
  w.fact = `my cat Mipsy${u} is allergic to fish`;
  w.intro = `My name is ${w.name}, my phone is ${w.phone}, my order ${w.order} is late and ${w.fact}.`;
  w.privateQ = `Where is my order ${w.order}, do you have my phone ${w.phone} for ${w.name}?`;
  w.privateA = `Hello ${w.name}, order ${w.order} ships soon; we will call ${w.phone}. Noted that ${w.fact}.`;
  w.stated = `This is ${w.name} calling, my phone is ${w.phone} and my order is ${w.order}.`;
  w.leakyA = `Sure ${w.name}, the zorblax${u} store opens at 9 am.`;
  w.secrets = [w.name, w.phone, w.order, `Mipsy${u}`];
  w.frames = {
    [w.generalQ]: { kind: "general", subject: "none", confidence: 0.9, question: w.generalQ,
      entities: [{ text: `zorblax${u} store`, type: "product" }] },
    [w.intro]: { kind: "personal", subject: "self", confidence: 0.9,
      entities: [{ text: w.name, type: "person" }, { text: w.phone, type: "phone" }, { text: w.order, type: "order_id" }] },
    [w.stated]: { kind: "personal", subject: "self", confidence: 0.9,
      entities: [{ text: w.name, type: "person" }, { text: w.phone, type: "phone" }, { text: w.order, type: "order_id" }] },
    [w.privateQ]: { kind: "personal", subject: "self", confidence: 0.9,
      entities: [{ text: w.order, type: "order_id" }] },
  };
  w.leaks = (obj) => {
    const text = JSON.stringify(obj, (k, v) => (v instanceof Buffer ? v.toString() : v)).toLowerCase();
    return w.secrets.filter((s) => text.includes(s.toLowerCase()));
  };
  return w;
}

// What the caller got if it came from the cache, null if the model had to answer.
const servedText = (result, modelReply) => (result.text === modelReply ? null : result.text);

function setup() {
  const w = words();
  const client = new CrowkisClient();
  const writes = [];
  const cset = client.cset.bind(client);
  client.cset = (...args) => { writes.push(args); return cset(...args); };
  const understander = { understand: (turn) => TurnFrame.fromDict(w.frames[turn]) };

  async function chatAsk(thread, texts, reply) {
    const agent = new Agent(`xchan-chat-${w.u}`, { client });
    const chat = new Chat(agent, understander, { system: "You are the store's assistant." });
    const history = [];
    const out = [];
    for (const text of texts) {
      history.push({ role: "user", content: text });
      out.push(await chat.turn(thread, [...history], async () => reply));
      history.push({ role: "assistant", content: out[out.length - 1].text });
    }
    return out;
  }

  async function voiceAsk(texts, reply, understood = true) {
    const extra = understood ? { classifier: new LLMClassifier(understander), rewriter: new LLMRewriter(understander) } : {};
    const session = voiceSession({ client, agentId: `xchan-voice-${w.u}`, ...extra });
    const out = [];
    for (const text of texts) out.push(await session.answer(text, async () => reply));
    return { out, session };
  }

  async function untilServed(ask, wait = FINDABLE_MS) {
    const deadline = Date.now() + wait;
    for (;;) {
      const served = await ask();
      if (served !== null || Date.now() > deadline) return served;
      await sleep(500);
    }
  }

  async function assertPrivateStayedPrivate(got) {
    assert.deepStrictEqual(w.leaks(got), [], "a private detail came back through the other channel");
    assert.deepStrictEqual(w.leaks(writes), [], "a private detail was written to the shared cache");
    assert.ok(writes.length, "the first channel saved nothing: this proves nothing");
    for (const question of [w.privateQ, w.intro, ...w.secrets]) {
      for (const segment of SEGMENTS) {
        const hit = await client.cgetHit(question, segment ? { segment } : {});
        assert.deepStrictEqual(w.leaks(hit), [], `raw lookup of ${question} in ${segment} found a detail`);
      }
    }
  }

  async function chatSaves() {
    const [general] = await chatAsk("t-general", [w.generalQ], w.generalA);
    assert.strictEqual(general.outcome, "saved", JSON.stringify(general));
    const priv = await chatAsk("t-private", [w.intro, w.privateQ], w.privateA);
    assert.ok(priv.every((r) => r.outcome !== "saved"), JSON.stringify(priv)); // never shared
    await sleep(1500);
  }

  async function voiceSaves() {
    const { out: [general], session } = await voiceAsk([w.generalQ], w.generalA);
    assert.ok(general.stored, JSON.stringify(general));
    for (const text of [w.intro, w.privateQ]) {
      const decision = await session.answer(text, async () => w.privateA);
      assert.ok(!decision.stored, JSON.stringify(decision)); // never shared
    }
    await sleep(1500);
  }

  async function assertStatedDetailsNotShared(firstStored, secondCaller) {
    assert.notStrictEqual(firstStored, true, "an answer repeating the caller's details was saved shared");
    assert.deepStrictEqual(w.leaks(writes), [], "a stated detail was written to the shared cache");
    await sleep(1500);
    assert.deepStrictEqual(w.leaks(await secondCaller()), [], "a second caller got the first caller's details");
  }

  return { assertStatedDetailsNotShared, w, client, chatAsk, voiceAsk, untilServed, assertPrivateStayedPrivate, chatSaves, voiceSaves };
}

const real = (name, options, fn) => test(name, { skip: REAL ? false : "needs a real server: CROWKIS_CONFORMANCE_SERVER=1", ...options }, async () => {
  const t = setup();
  try { await fn(t); } finally { await t.client.close(); }
});

real("chat to voice keeps private details private", {}, async (t) => {
  await t.chatSaves();
  for (const understood of [true, false]) {
    const { out } = await t.voiceAsk([t.w.generalQ, t.w.intro, t.w.privateQ], "Sorry, one moment.", understood);
    await t.assertPrivateStayedPrivate(out);
  }
});

// By design (v4 P5 item 5): every segment holds channel=<name>, so channels never serve each other's answers.
real("chat to voice does not serve the general answer", {}, async (t) => {
  await t.chatSaves();
  const got = await t.untilServed(async () => servedText((await t.voiceAsk([t.w.generalQ], "LLM-VOICE")).out[0], "LLM-VOICE"), SEPARATE_MS);
  assert.strictEqual(got, null);
});

real("voice to chat keeps private details private", {}, async (t) => {
  await t.voiceSaves();
  const got = await t.chatAsk("t-other", [t.w.generalQ, t.w.intro, t.w.privateQ], "Sorry, one moment.");
  await t.assertPrivateStayedPrivate(got);
});

real("voice to chat does not serve the general answer", {}, async (t) => { // P5 item 5, as above
  await t.voiceSaves();
  const got = await t.untilServed(async () => servedText((await t.chatAsk("t-g2", [t.w.generalQ], "LLM-CHAT"))[0], "LLM-CHAT"), SEPARATE_MS);
  assert.strictEqual(got, null);
});

real("a voice answer repeating stated details is not shared", {}, async (t) => {
  const { session } = await t.voiceAsk([t.w.stated], "Thank you, noted.");
  const first = await session.answer(t.w.generalQ, async () => t.w.leakyA);
  await t.assertStatedDetailsNotShared(first.stored, async () => (await t.voiceAsk([t.w.generalQ], "LLM-VOICE")).out);
});

real("a chat answer repeating stated details is not shared", {}, async (t) => {
  const first = (await t.chatAsk("t-stated", [t.w.stated, t.w.generalQ], t.w.leakyA))[1];
  assert.notStrictEqual(first.outcome, "saved", JSON.stringify(first));
  await t.assertStatedDetailsNotShared(false, () => t.chatAsk("t-second", [t.w.generalQ], "LLM-CHAT"));
});

real("control: chat to chat shares the general answer", {}, async (t) => {
  await t.chatSaves();
  const got = await t.untilServed(async () =>
    servedText((await t.chatAsk(`t-${crypto.randomBytes(3).toString("hex")}`, [t.w.generalQ], "LLM-CHAT"))[0], "LLM-CHAT"));
  assert.strictEqual(got, t.w.generalA);
});

real("control: voice to voice shares the general answer", {}, async (t) => {
  await t.voiceSaves();
  const got = await t.untilServed(async () => servedText((await t.voiceAsk([t.w.generalQ], "LLM-VOICE")).out[0], "LLM-VOICE"));
  assert.strictEqual(got, t.w.generalA);
});
