"use strict";

// Hit rules: when a confident hit still goes to the model instead of being spoken.
// A family of small rules, in the order a hit is checked.

const { Verdict } = require("../../turns/verdict.js");
const { COMMITMENTS, PII_PLACEHOLDER, speakable } = require("../../understanding/wordRules.js");

const CACHE_ROUTE = "cache";
const SLOT_MISSING_REASON =
  "the shared answer shape has a slot this call has no value for; " +
  "speaking a half-filled answer is worse than a model call";
const PLACEHOLDER_REASON =
  "the cached answer holds a placeholder the server put in place of a caller's detail; " +
  "reading it aloud is worse than a model call";
const DIFFERENT_QUESTION_REASON =
  "the cached answer was saved for a different question (it asks about something " +
  "this one does not); a model call is better than a wrong answer";
const SHORT_TURN_REASON =
  "a short turn is only answered from cache once the answer has been " +
  "judged to stand on its own, and this one has not";
const SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)";

/** A hit below the spoken-answer bar (or a miss) goes to the model. */
class ConfidenceBar {
  get name() {
    return "ConfidenceBar";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (cached.hit.route === CACHE_ROUTE) return null;
    return new Verdict(this.name, `confidence below the spoken-answer bar of ${cached.turn.call.serveAbove}`, ["inferred"]);
  }
}

/** A shared answer shape with a slot this call has no value for is never half spoken. */
class TemplateSlotMissing {
  get name() {
    return "TemplateSlotMissing";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!cached.turn.isPersonal || cached.answer !== null) return null;
    return new Verdict(this.name, SLOT_MISSING_REASON, ["refusedPrivate", "inferred"]);
  }
}

/** An answer holding a placeholder the server put in place of a caller's detail is never read aloud. */
class PiiPlaceholder {
  get name() {
    return "PiiPlaceholder";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!PII_PLACEHOLDER.test(cached.answer)) return null;
    return new Verdict(this.name, PLACEHOLDER_REASON, ["refusedPrivate", "inferred"]);
  }
}

/** A near hit saved for a question that asks about something else is not served. */
class DifferentQuestion {
  get name() {
    return "DifferentQuestion";
  }

  get floor() {
    return false;
  }

  async check(cached) {
    const turn = cached.turn;
    if (turn.isPersonal || cached.hit.exact) return null;
    const spentMs = performance.now() - cached.started;
    if (!(await turn.call.answersAnotherQuestion(turn.key, cached.answer, spentMs))) return null;
    return new Verdict(this.name, DIFFERENT_QUESTION_REASON, ["differentQuestion", "inferred"]);
  }
}

/** A short turn is served only an exact match the server's decision engine has vouched for. */
class ShortTurnUnvouched {
  get name() {
    return "ShortTurnUnvouched";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!cached.turn.isShort || (cached.hit.vouched && cached.hit.exact)) return null;
    return new Verdict(this.name, SHORT_TURN_REASON, ["inferred"]);
  }
}

/**
 * A commitment (a price, a refund, a policy) is spoken only as the call's `commitments` setting
 * allows: by default, only for the exact same question.
 */
class CommitmentRewording {
  get name() {
    return "CommitmentRewording";
  }

  get floor() {
    return false;
  }

  check(cached) {
    const commitments = cached.turn.call.commitments;
    if (!cached.hit.commitment || COMMITMENTS[commitments](cached.hit)) return null;
    const reason =
      "the cached answer is a commitment (a price, a refund, a policy) and " +
      `commitments="${commitments}" does not allow speaking this match`;
    return new Verdict(this.name, reason, ["heldCommitments", "inferred"]);
  }
}

/** An answer written for a screen (a link, code or markup) is not spoken. */
class ScreenOnlyAnswer {
  get name() {
    return "ScreenOnlyAnswer";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (speakable(cached.answer)) return null;
    return new Verdict(this.name, SCREEN_REASON, ["unspeakable", "inferred"]);
  }
}

module.exports = {
  CommitmentRewording,
  ConfidenceBar,
  DifferentQuestion,
  PiiPlaceholder,
  ScreenOnlyAnswer,
  ShortTurnUnvouched,
  TemplateSlotMissing,
};
