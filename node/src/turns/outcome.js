"use strict";

/**
 * What happened to a model's answer: the words callers see in `decision.notStored`, a voice record's
 * `outcome`, Chat's outcomes and its "answer" events. Named constants, like COUNTER.
 */
const OUTCOME = Object.freeze({
  SAVED: "saved",
  TEMPLATE: "template",
  KEPT: "kept",
  PRIVATE: "private",
  NON_ANSWER: "non_answer",
  NOT_SAVED: "not_saved",
  INTERRUPTED: "interrupted",
  NOT_SHARED: "not_shared",
  CANCELLED: "cancelled",
  STALE: "stale",
  SLOW_WRITE: "slow_write",
  REFUSED: "refused",
});

/** Chat's form of an outcome with its reason: "refused:<why>". */
function because(outcome, why) {
  return `${outcome}:${why}`;
}

module.exports = { OUTCOME, because };
