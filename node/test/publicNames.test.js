"use strict";

// v4 P5.6: the public, stable names apps import (they never move with the internals). The same cases as
// python/tests/test_public_names.py.

const assert = require("node:assert");
const { test } = require("node:test");
const crowkis = require("../index.js");
const privacy = require("../src/privacy.js");

test("the routes are at the root", () => {
  assert.deepStrictEqual(
    [crowkis.AGENT, crowkis.PERSONAL, crowkis.SHARED, crowkis.TASK, crowkis.TOOLS, crowkis.URGENT, crowkis.FILLER],
    ["agent", "personal", "shared", "task", "tools", "urgent", "filler"]);
});

test("the privacy word rules have public names", () => {
  assert.strictEqual(privacy.isPersonal("where is my order 48213"), true);
  assert.strictEqual(privacy.isContextDependent("and how long will that take"), true);
  assert.strictEqual(privacy.isContextDependent("what is your refund policy"), false);
  const shape = privacy.abstract("Your order 48213 ships today.", { order: "48213" });
  assert.strictEqual(shape, "Your order {order} ships today.");
  assert.strictEqual(privacy.leaks(shape, { order: "48213" }), false);
  assert.strictEqual(privacy.fill(shape, { order: "77" }), "Your order 77 ships today.");
  assert.ok(new RegExp(privacy.SLOT.source).test(shape));
  assert.ok(privacy.CONTEXT_BOUND_THRESHOLD > 0.9);
});
