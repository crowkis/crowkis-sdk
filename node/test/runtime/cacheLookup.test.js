"use strict";

// v4 P3: CacheLookup refuses a late hit and fails open, as python/tests/runtime/test_cache_lookup.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { CacheLookup } = require("../../src/runtime/cacheLookup.js");

const HIT = { route: "cache", answer: "Nine to five.", confidence: 0.99 };

test("a hit that came back after the budget", async () => {
  const started = performance.now() - 1000; // the budget was spent before the hit came back
  const late = await new CacheLookup().find(async () => HIT, started, 100);
  assert.strictEqual(late.verdict.rule, "LookupDeadline");
});

test("an unreachable cache means the model answers", async () => {
  const { verdict } = await new CacheLookup().find(async () => { throw new Error("down"); }, performance.now(), null);
  assert.strictEqual(verdict.rule, "CacheUnavailable");
});
