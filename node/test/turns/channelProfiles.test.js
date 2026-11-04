"use strict";

// v4 P4 step 5: voiceSession({ channel }) takes the budgets it is not given from the channel's
// profile. The same cases as python/tests/turns/test_channel_profiles.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { CrowkisClient } = require("../../index.js");
const { Channel, REALTIME, VOICE } = require("../../src/turns/values.js");
const { voiceSession } = require("../../src/channels/voiceSession.js");

function factory(options = {}) {
  return voiceSession({ client: new CrowkisClient({ port: 1 }), ...options });
}

test("must still work: a voice call by default", () => {
  const session = factory();
  assert.strictEqual(session.channel, VOICE);
  assert.strictEqual(session._call.channel, VOICE);
  assert.strictEqual(session.latencyBudgetMs, 250);
});

test("a channel by name or profile", () => {
  assert.strictEqual(factory({ channel: "realtime" }).channel, REALTIME);
  assert.strictEqual(factory({ channel: REALTIME }).channel, REALTIME);
  assert.strictEqual(Channel.of(" Voice "), VOICE);
});

test("the budgets come from the channel unless given", () => {
  const custom = new Channel({ name: "slow-line", isolatesContext: true, budgetMs: 400, audio: true, spoken: true,
    savesAnswers: true, understandBudgetMs: 600 });
  assert.strictEqual(factory({ channel: custom }).latencyBudgetMs, 400);
  assert.strictEqual(factory({ channel: custom, latencyBudgetMs: 100 }).latencyBudgetMs, 100);
});

test("must still work: null turns the budget off", () => {
  assert.strictEqual(factory({ latencyBudgetMs: null }).latencyBudgetMs, null);
});

test("an unknown channel is an error", () => {
  assert.throws(() => factory({ channel: "fax" }));
});
