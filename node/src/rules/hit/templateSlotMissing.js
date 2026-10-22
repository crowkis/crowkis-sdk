"use strict";

// The TemplateSlotMissing rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

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

module.exports = { TemplateSlotMissing };
