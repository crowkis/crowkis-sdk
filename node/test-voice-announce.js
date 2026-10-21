"use strict";
// announce() on a real server: a notice stops a contradicted answer being served (T4).
// Mirrors python/tests/test_voice_announce.py. Needs a real server with the decision engine:
//   CROWKIS_CONFORMANCE_SERVER=1 CROWKIS_HOST=... CROWKIS_TENANT=... node --test test-voice-announce.js
const assert = require("node:assert");
const { test } = require("node:test");
const { CrowkisClient } = require("./index.js");
const { voiceSession, _waitForWrites: waitForWrites } = require("./voice.js");
const { waitForAudioStores } = require("./agent.js");

const REAL = process.env.CROWKIS_CONFORMANCE_SERVER === "1";
const sleep = (ms) => new Promise((done) => setTimeout(done, ms));
const pick = (letters) => letters[Math.floor(Math.random() * letters.length)];

test("a notice stops the answer it contradicts being served", { skip: !REAL && "needs a real server" }, async (t) => {
  const client = new CrowkisClient();
  t.after(() => client.close());
  // A made-up place, so no earlier run's answer is near it.
  let place = "zor";
  for (let i = 0; i < 3; i += 1) place += pick("bcdfghklmnprstvz") + pick("aeiou");
  const question = `What time does the ${place} greenhouse close?`;
  if (!(await client.cdecision(question)).engine) {
    t.skip("the server has no decision engine, so it keeps no notices");
    return;
  }
  // No latency budget: a slow lookup must not decide the test either way.
  const session = () => voiceSession({ client, latencyBudgetMs: null });
  const first = await session().answer(question, async () => `The ${place} greenhouse closes at nine in the evening.`);
  await waitForWrites();
  await waitForAudioStores();
  assert.strictEqual(first.stored, true, first.notStored);
  let served = false;
  for (let i = 0; i < 10 && !served; i += 1) { // a new answer becomes findable within a few seconds
    await sleep(1000);
    served = (await session().decide(question)).action === "serve";
  }
  assert.ok(served, "the saved answer was never served to the next caller");

  const notice = await session().agent.announce(`the ${place} greenhouse closes at 3pm because of the holiday`, { lasts: 60 });
  t.after(() => client.cnoticeClear(notice.id));
  await sleep(500);
  const later = await session().decide(question);
  assert.notStrictEqual(later.action, "serve", later.text);
});
