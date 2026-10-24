"use strict";
// Chat works on every Node the package supports (">=18"), including those without
// zlib.crc32 (added in Node 20.15 / 22.2), and its tailoring hash stays the same as
// Python's zlib.crc32 (CI1). The expected hashes come from Python's crowkis.verify.
const test = require("node:test");
const assert = require("node:assert");
const zlib = require("node:zlib");
const { RuleChecker } = require("./verify.js");

const CASES = [
  [["I am allergic to peanuts"], "is pad thai safe for someone with a peanut allergy", "c98c6f50"],
  [["I have diabetes and high blood pressure"], "which snacks are fine with diabetes and high blood pressure", "6376d381"],
  [["mujhe peanut allergy hai"], "kya pad thai peanut allergy wale ke liye safe hai", "bbb6152a"],
  [["I live in München"], "what time do shops in München close", "8b742f89"],
];

function tailoring(stated, question) {
  return RuleChecker._tailoring({ entities: [] }, { stated, facts: [] }, question);
}

test("the tailoring hash matches Python's", () => {
  for (const [stated, question, hash] of CASES) assert.strictEqual(tailoring(stated, question), hash, question);
});

test("the tailoring hash needs no zlib.crc32 (Node 18)", (t) => {
  const crc32 = zlib.crc32;
  t.after(() => {
    zlib.crc32 = crc32;
  });
  zlib.crc32 = undefined;
  for (const [stated, question, hash] of CASES) assert.strictEqual(tailoring(stated, question), hash, question);
});

test("a question anyone could ask has no tailoring hash", () => {
  assert.strictEqual(tailoring([], "what time do you open"), null);
});
