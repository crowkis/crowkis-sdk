"use strict";

// The DifferentQuestion rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

const DIFFERENT_QUESTION_REASON =
  "the cached answer was saved for a different question (it asks about something " +
  "this one does not); a model call is better than a wrong answer";

/** A near hit saved for a question that asks about something else is not served. */
class DifferentQuestion {
  get name() {
    return "DifferentQuestion";
  }

  get floor() {
    return false;
  }

  // Asks the server (the questions the answer was saved for) only for a near hit: then a promise.
  check(cached) {
    const turn = cached.turn;
    if (turn.isPersonal || cached.hit.exact) return null;
    const spentMs = performance.now() - cached.started;
    return Promise.resolve(turn.call.answersAnotherQuestion(turn.key, cached.answer, spentMs)).then((another) =>
      (another ? new Verdict(this.name, DIFFERENT_QUESTION_REASON, [COUNTER.DIFFERENT_QUESTION, COUNTER.INFERRED]) : null));
  }
}

module.exports = { DifferentQuestion };
