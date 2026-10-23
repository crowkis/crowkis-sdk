"use strict";

// The ToldDetailDropped rule (stage 1, question; Chat, "V7_lost_detail", checked once the rule checker would share).

const { Verdict } = require("../../turns/verdict.js");
const { wordDigest } = require("../../state/callState.js");
const { NUMWORDS } = require("../../understanding/frameWords.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");

/** A place, month or number the caller told ("Goa in December") is missing from the question. */
class ToldDetailDropped {
  get name() {
    return "ToldDetailDropped";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const words = wordsOf(turn.question || "");
    const asked = new Set([...words.map(wordDigest), ...words.map((w) => wordDigest(NUMWORDS[w] || w))]); // "three" is "3"
    if (!turn.state.details.some((d) => !asked.has(d))) return null;
    return new Verdict(this.name, "V7_lost_detail");
  }
}

module.exports = { ToldDetailDropped };
