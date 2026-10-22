"use strict";

// The UnresolvedReference rule (stage 1, question; Chat, V10).

const { Verdict } = require("../../turns/verdict.js");
const { CONTRACTION, FUNCTION, QUESTION_WORDS, REFERRING, toks } = require("../../understanding/frameWords.js");

/**
 * The model says the turn leans on the chat ("how far is it from London?") but the turn or its
 * question says "it" and the question names nothing new from the chat (a neutral "population" names
 * nothing; "Who is their president?" -> "Who is the president?" dropped it): the reference was not
 * resolved. A rewrite that resolved it ("Is it safe to eat pad thai in Thailand?") keeps a filler
 * "it" and is fine.
 */
class UnresolvedReference {
  get name() {
    return "UnresolvedReference";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const saidList = toks(turn.text);
    const said = new Set(saidList);
    const qwords = toks(turn.question);
    const named = qwords.some((w) => !said.has(w) && !FUNCTION.has(w) && !QUESTION_WORDS.has(w) && !CONTRACTION.has(w));
    if (!(turn.frame.usesState && [...qwords, ...saidList].some((w) => REFERRING.has(w)) && !named)) return null;
    return new Verdict(this.name, "V10_unresolved");
  }
}

module.exports = { UnresolvedReference };
