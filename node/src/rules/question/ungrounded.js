"use strict";

// The Ungrounded rule (stage 1, question; Chat, V6).

const { Verdict } = require("../../turns/verdict.js");
const { FUNCTION, QUESTION_WORDS, stem, toks } = require("../../understanding/frameWords.js");

const SHOWN_WORDS = 3;

/** A content word of the key that is not in the turn or the call state (grounding). */
class Ungrounded {
  get name() {
    return "Ungrounded";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const added = Ungrounded._ungrounded(turn.question, turn.text, turn.state);
    if (!added.length) return null;
    return new Verdict(this.name, "V6_ungrounded:" + added.slice(0, SHOWN_WORDS).join(","));
  }

  static _ungrounded(question, text, state) {
    const source = new Set(toks(text));
    for (const t of state.groundingSources()) for (const w of toks(t)) source.add(w);
    const stems = new Set([...source].map(stem));
    return toks(question).filter((w) => !FUNCTION.has(w) && !source.has(w) && !stems.has(stem(w)) && !QUESTION_WORDS.has(w));
  }
}

module.exports = { Ungrounded };
