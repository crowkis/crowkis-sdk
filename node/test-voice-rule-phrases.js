"use strict";
// What the voice rules decide for 277 phrases said on their own (T2, 2026-10-21).
// Mirrors python/tests/test_voice_rule_phrases.py; fixtures/voice-rule-phrases.json is shared,
// so the two languages cannot drift. A change that moves a phrase towards "share" loosens
// privacy: update the fixture only on purpose, with a note.
const assert = require("node:assert");
const fs = require("node:fs");
const path = require("node:path");
const { test } = require("node:test");
const { _isPersonal: isPersonal, _isContextDependent: isContextDependent } = require("./voice.js");

const FIXTURE = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "fixtures", "voice-rule-phrases.json"), "utf8"));

const verdict = (phrase) => (isPersonal(phrase) ? "never" : isContextDependent(phrase) ? "follow" : "share");

test("every phrase gets its verdict", () => {
  const wrong = FIXTURE.phrases.filter((c) => verdict(c.phrase) !== c.verdict)
    .map((c) => `${c.category}: "${c.phrase}" is ${verdict(c.phrase)}, expected ${c.verdict}`);
  assert.deepStrictEqual(wrong, []);
});

test("the fixture covers every kind", () => {
  assert.deepStrictEqual(new Set(FIXTURE.phrases.map((c) => c.verdict)), new Set(["never", "follow", "share"]));
  assert.ok(FIXTURE.phrases.length >= 277);
});
