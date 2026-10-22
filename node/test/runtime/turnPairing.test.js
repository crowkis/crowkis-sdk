"use strict";

// v4 P2: TurnPairing alone, the same cases as python/tests/runtime/test_turn_pairing.py.

const assert = require("node:assert");
const { test } = require("node:test");
const { TurnPairing } = require("../../src/runtime/turnPairing.js");

test("an answer to the latest turn carries what decide offered", () => {
  const pairing = new TurnPairing();
  const turn = pairing.begin();
  pairing.start(0);
  pairing.offer(turn, true);
  assert.deepStrictEqual(pairing.settle(turn), [turn, true]);
  assert.strictEqual(pairing.open, false);
});

test("an answer to an older turn is dropped", () => {
  const pairing = new TurnPairing();
  const old = pairing.begin();
  pairing.offer(old, true);
  pairing.begin();
  assert.strictEqual(pairing.settle(old), null);
});

test("a newer turn's offer is never overwritten by an older one", () => {
  const pairing = new TurnPairing();
  const old = pairing.begin();
  const fresh = pairing.begin();
  pairing.offer(fresh, false);
  pairing.offer(old, true);
  assert.deepStrictEqual(pairing.settle(fresh), [fresh, false]);
});

test("a barge-in trims the open turn and drops its answer", () => {
  const pairing = new TurnPairing();
  const turn = pairing.begin();
  pairing.start(3);
  const trimmed = [];
  assert.strictEqual(pairing.cancel((mark) => trimmed.push(mark)), true);
  assert.deepStrictEqual(trimmed, [3]);
  assert.strictEqual(pairing.cancel((mark) => trimmed.push(mark)), false);
  assert.strictEqual(pairing.movedOn(turn), true);
  assert.strictEqual(pairing.settle(turn), null);
});
