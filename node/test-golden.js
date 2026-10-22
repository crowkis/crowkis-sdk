"use strict";

// v4 P0: today's decisions, pinned (fixtures/golden/<pipeline>/<suite>.json), the same files
// as python/tests/test_golden.py. Every v4 refactor phase must reproduce them exactly; a
// difference is a behaviour change and needs the owner's OK.

const assert = require("node:assert");
const fs = require("node:fs");
const { test } = require("node:test");
const { ChatReplay, VoiceReplay, goldenPath, replay, suites } = require("./golden.js");

for (const pipeline of [new VoiceReplay(), new ChatReplay()]) {
  for (const [suite, calls] of Object.entries(suites())) {
    test(`golden ${pipeline.pipeline} decisions: ${suite}`, async () => {
      const expected = JSON.parse(fs.readFileSync(goldenPath(pipeline.pipeline, suite), "utf8"));
      assert.deepStrictEqual(await replay(pipeline, calls), expected);
    });
  }
}
