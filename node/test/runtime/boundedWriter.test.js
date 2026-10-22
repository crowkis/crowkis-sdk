"use strict";

// v4 P2: BoundedWriter alone, the same cases as python/tests/runtime/test_bounded_writer.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { BoundedWriter } = require("../../src/runtime/boundedWriter.js");

const DEADLINE_MS = 50;

function writer(pending, counts, cap = 10) {
  return new BoundedWriter(pending, () => cap, (name) => counts.push(name), () => {});
}

test("a quick write is done", async () => {
  const counts = [];
  assert.strictEqual(await writer(new Set(), counts).write(async () => {}, DEADLINE_MS), null);
  assert.deepStrictEqual(counts, []);
});

test("a slow write is not confirmed and finishes later", async () => {
  const counts = [];
  const pending = new Set();
  let release;
  const verdict = await writer(pending, counts).write(() => new Promise((resolve) => { release = resolve; }), DEADLINE_MS);
  assert.deepStrictEqual([verdict.rule, verdict.outcome], ["BoundedWrite", "slow_write"]);
  assert.match(verdict.reason, /not confirmed/);
  assert.deepStrictEqual(counts, ["slowWrites"]);
  release();
  await Promise.allSettled([...pending]);
  assert.strictEqual(pending.size, 0);
});

test("past the cap a new answer is not written", async () => {
  const pending = new Set();
  const slow = writer(pending, [], 1);
  let release;
  await slow.write(() => new Promise((resolve) => { release = resolve; }), DEADLINE_MS);
  const verdict = await slow.write(async () => {}, DEADLINE_MS);
  assert.match(verdict.reason, /not written/);
  release();
});

test("an error before the deadline is thrown", async () => {
  await assert.rejects(writer(new Set(), []).write(async () => { throw new Error("refused"); }, 1000), /refused/);
});
