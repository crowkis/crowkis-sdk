"use strict";

// Stage 2 rules (hit): may a cached answer be spoken for this turn.

const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { PII_PLACEHOLDER, speakable } = require("../../understanding/wordRules/index.js");

// Commitment policies: how a cached commitment (a price, a refund, a policy) may be spoken. A Strategy per
// voiceSession({ commitments }) setting: serve any match, only the same question, or never.
const COMMITMENT_POLICIES = Object.freeze({
  serve: () => true,
  exact: (hit) => hit.exact,
  never: () => false,
});

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
    const { hit } = cached;
    if (!(hit.commitment || hit.unjudged) || COMMITMENT_POLICIES[commitments](hit)) return null;
    const reason =
      (hit.commitment
        ? "the cached answer is a commitment (a price, a refund, a policy)"
        : "the cached answer has not been judged yet, so it may be a commitment") +
      ` and commitments="${commitments}" does not allow speaking this match`;
    return new Verdict(this.name, reason, [COUNTER.HELD_COMMITMENTS, COUNTER.INFERRED]);
  }
}

/** A hit below the spoken-answer bar (or a miss) goes to the model. */
class ConfidenceBar {
  get name() {
    return "ConfidenceBar";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (cached.hit.isConfident) return null;
    return new Verdict(this.name, `confidence below the spoken-answer bar of ${cached.turn.call.serveAbove}`, [COUNTER.INFERRED]);
  }
}

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

const PLACEHOLDER_REASON =
  "the cached answer holds a placeholder the server put in place of a caller's detail; " +
  "reading it aloud is worse than a model call";

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
    return new Verdict(this.name, PLACEHOLDER_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

const SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)";

/** An answer written for a screen (a link, code or markup) is not spoken. */
class ScreenOnlyAnswer {
  get name() {
    return "ScreenOnlyAnswer";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!cached.turn.call.channel.spoken || speakable(cached.answer)) return null;
    return new Verdict(this.name, SCREEN_REASON, [COUNTER.UNSPEAKABLE, COUNTER.INFERRED]);
  }
}

const SHORT_TURN_REASON =
  "a short turn is only answered from cache once the answer has been " +
  "judged to stand on its own, and this one has not";

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
    return new Verdict(this.name, SHORT_TURN_REASON, [COUNTER.INFERRED]);
  }
}

const SLOT_MISSING_REASON =
  "the shared answer shape has a slot this call has no value for; " +
  "speaking a half-filled answer is worse than a model call";

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
    return new Verdict(this.name, SLOT_MISSING_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

module.exports = { CommitmentRewording, ConfidenceBar, DifferentQuestion, PiiPlaceholder, ScreenOnlyAnswer, ShortTurnUnvouched, TemplateSlotMissing };
