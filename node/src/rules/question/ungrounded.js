"use strict";

// The Ungrounded rule (stage 1, question; Chat, V6).

const { Verdict } = require("../../turns/verdict.js");
const { FUNCTION, QUESTION_WORDS, stem, toks } = require("../../understanding/frameWords.js");

const SHOWN_WORDS = 3;
// A stem that starts another of at least this many letters is the same word ("visit", "visitor").
const SHARED_STEM = 5;

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
    return toks(question).filter((w) => !FUNCTION.has(w) && !source.has(w) && !Ungrounded._grounded(stem(w), stems)
      && !QUESTION_WORDS.has(w));
  }

  /** The stem, or one it starts or is started by (v4, misfire B03: "visitors" after "visiting"). */
  static _grounded(wordStem, stems) {
    if (stems.has(wordStem)) return true;
    return [...stems].some((other) => Math.min(wordStem.length, other.length) >= SHARED_STEM
      && (wordStem.startsWith(other) || other.startsWith(wordStem)));
  }
}

module.exports = { Ungrounded };
