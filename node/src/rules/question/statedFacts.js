"use strict";

// The StatedFacts rule (stage 1, question; Chat, V7).

const { Verdict } = require("../../turns/verdict.js");
const { FactRelevanceCheck } = require("../../understanding/factRelevance.js");
const { CLAUSE_START, FUNCTION, GENERIC_FACT, stem, toks } = require("../../understanding/frameWords.js");

/**
 * A fact the caller stated in this chat (an allergy, an age, a trip) that the question does not
 * carry. Fixed code, so the allergy case never rests on the model having tagged the allergy: the
 * question must keep at least one content word of each such turn. A turn with no readable word
 * (another script) cannot be checked, so it keeps the question private.
 *
 * v4: a stated turn the frame confidently tags as not changing this answer may be left out
 * (FactRelevanceCheck); an allergy, a medication, a pregnancy or an age never may.
 */
class StatedFacts {
  constructor({ relevance = new FactRelevanceCheck() } = {}) {
    this._relevance = relevance;
  }

  get name() {
    return "StatedFacts";
  }

  get floor() {
    return false;
  }

  check(turn) {
    for (const dropped of StatedFacts._droppedStatements(turn.state, turn.question)) {
      if (!this._relevance.irrelevant(dropped, turn.frame)) return new Verdict(this.name, "V7_lost:" + dropped);
    }
    return null;
  }

  static *_droppedStatements(state, question) {
    const qstems = new Set(toks(question).map(stem));
    for (const turn of state.stated) {
      let words = toks(turn).filter((w) => !FUNCTION.has(w) && (w.length > 2 || /^\d+$/.test(w)));
      // "allergies" alone does not carry "allergic to penicillin": the specific word must be there.
      const specific = words.filter((w) => !GENERIC_FACT.has(stem(w)));
      if (specific.length) words = specific;
      if (!words.length || !words.some((w) => qstems.has(stem(w))) || StatedFacts._dropsAListedItem(turn, qstems)) {
        yield turn;
      }
    }
  }

  /** Every item of a list is carried: "penicillin and peanuts" is not "peanuts". */
  static _dropsAListedItem(turn, qstems) {
    const all = toks(turn);
    for (let i = 0; i < all.length; i++) {
      // "and I live alone" starts a new clause; it is not a list.
      if ((all[i] !== "and" && all[i] !== "or") || (i + 1 < all.length && CLAUSE_START.has(all[i + 1]))) continue;
      for (const side of [all.slice(0, i).reverse(), all.slice(i + 1)]) {
        const item = side.find((x) => !FUNCTION.has(x));
        if (item && (item.length > 2 || /^\d+$/.test(item)) && !GENERIC_FACT.has(stem(item)) && !qstems.has(stem(item))) return true;
      }
    }
    return false;
  }
}

module.exports = { StatedFacts };
