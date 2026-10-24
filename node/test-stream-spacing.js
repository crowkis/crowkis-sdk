"use strict";
// A cached answer streamed back in chunks reads exactly as it was stored (X1).
// Python: tests/test_stream_spacing.py.
const test = require("node:test");
const assert = require("node:assert");
const { CrowkisClient } = require("./index.js");
const { cases: FIXTURE } = require("../fixtures/stream-chunks.json");

const ANSWERS = [
  "It waters at dawn for ten minutes.",
  "One two three four five six seven eight nine.",
  "Line one.\nLine two has   three spaces.\n\nA new paragraph.",
  "  Leading and trailing spaces.  ",
  "Short.",
  "हमारा स्टोर सुबह नौ बजे से शाम पांच बजे तक खुला रहता है।",
  "Aapka refund 5–7 business days mein aa jayega, sir ji.",
];

async function streamed(answer, options = {}) {
  const cache = new CrowkisClient({ lazyConnect: true });
  cache.cget = async () => Buffer.from(answer, "utf8");
  const never = () => {
    throw new Error("a cache hit never calls the model");
  };
  const chunks = [];
  for await (const chunk of cache.stream("q", never, { delayMs: 0, ...options })) chunks.push(chunk);
  return chunks;
}

test("the chunks join back to the cached answer", async () => {
  for (const answer of ANSWERS) {
    for (const chunkTokens of [1, 2, 4, 128]) {
      assert.strictEqual((await streamed(answer, { chunkTokens })).join(""), answer, `${chunkTokens}: ${answer}`);
    }
  }
});

test("a hit still streams in several chunks", async () => {
  const chunks = await streamed("It waters at dawn for ten minutes.");
  assert.strictEqual(chunks.length, 2);
  assert.strictEqual(chunks[0].trim(), "It waters at dawn");
});

test("the chunks match the shared fixture", async () => {  // X5: the same chunks as Python
  for (const { text, chunk_tokens: chunkTokens, chunks } of FIXTURE) {
    assert.deepStrictEqual(await streamed(text, { chunkTokens }), chunks, `${chunkTokens}: ${JSON.stringify(text)}`);
  }
});

test("an answer of only spaces streams nothing", async () => {
  assert.deepStrictEqual(await streamed("   "), []);
});
