"use strict";

// The LostDetail rule (stage 1, question; Chat, V7).

const { Verdict } = require("../../turns/verdict.js");
const { DETAIL_TYPES } = require("../../../turn.js");
const { FUNCTION, stem, toks } = require("../../understanding/frameWords.js");

/** An answer-relevant detail of the turn (a product, a time, a place) missing from the key. */
class LostDetail {
  get name() {
    return "LostDetail";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const lost = LostDetail._lostDetail(turn.frame, turn.question);
    if (!lost) return null;
    return new Verdict(this.name, "V7_lost:" + lost);
  }

  static _lostDetail(frame, question) {
    const qstems = new Set(toks(question).map(stem));
    const attrText = Object.values(frame.attributes).map((a) => `${a.value} ${a.normalised}`).join(" ").toLowerCase();
    for (const e of frame.entities) {
      if (e.answerRelevant && !e.identifying && DETAIL_TYPES.has(e.type)) {
        const words = toks(e.text).filter((w) => !FUNCTION.has(w));
        if (words.length && !words.some((w) => qstems.has(stem(w))) && !words.some((w) => attrText.includes(w))) return e.text;
      }
    }
    return null;
  }
}

module.exports = { LostDetail };
