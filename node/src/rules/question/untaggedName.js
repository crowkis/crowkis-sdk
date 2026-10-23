"use strict";

// The UntaggedName rule (stage 1, question; Chat, "V5_untagged_name", checked once the rule checker would share).

const { Verdict } = require("../../turns/verdict.js");
const { wordDigest } = require("../../../callstate.js");
const { NOT_GENERAL_TYPES } = require("../../../turn.js");
const { CALENDAR, COMMON_ACRONYMS, FUNCTION } = require("../../understanding/frameWords.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");

/**
 * A word in the shared question with a capital ("Priya", "PRIYA", "McKenzie"), or in a script without
 * capitals, that the understanding model did not tag as a place, thing or topic, that is no month or
 * day, and that no earlier shared turn of this chat said. Fixed code cannot tell "Priya" from
 * "France" or "SSO"; the model's tag can (it is asked to tag every one).
 */
class UntaggedName {
  get name() {
    return "UntaggedName";
  }

  get floor() {
    return true;
  }

  check(turn) {
    const state = turn.state;
    const allowed = new Set(turn.frame.entities.filter((e) => !e.identifying && !NOT_GENERAL_TYPES.has(e.type)).flatMap((e) => wordsOf(e.text)));
    for (const w of [...CALENDAR, ...COMMON_ACRONYMS, ...wordsOf(state.activeQuestion || ""), ...wordsOf(state.lastReply)]) allowed.add(w);
    const flagged = new Set();
    (String(turn.question || "").match(/\p{L}+/gu) || []).forEach((word, i) => {
      const low = word.toLowerCase();
      if (word === "I" || (i === 0 && FUNCTION.has(low))) return; // "What ...", "How ..."
      if (/[\p{Lu}\p{Lt}\p{Lo}]/u.test(word)) flagged.add(low);
    });
    if (![...flagged].some((w) => !allowed.has(w) && !state.details.includes(wordDigest(w)))) return null;
    return new Verdict(this.name, "V5_untagged_name");
  }
}

module.exports = { UntaggedName };
