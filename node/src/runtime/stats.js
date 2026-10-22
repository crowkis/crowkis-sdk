"use strict";

/** The counters a voice session keeps; each value is the session property stats() reads. */
const COUNTER = Object.freeze({
  SERVED: "served",
  FILLED: "filled",
  INFERRED: "inferred",
  REFUSED_SHORT: "refusedShort",
  REFUSED_PRIVATE: "refusedPrivate",
  UNCACHEABLE_PERSONAL: "uncacheablePersonal",
  OVER_BUDGET: "overBudget",
  BARGE_INS: "bargeIns",
  LOOKUP_ERRORS: "lookupErrors",
  LEARN_ERRORS: "learnErrors",
  SLOW_WRITES: "slowWrites",
  DIFFERENT_QUESTION: "differentQuestion",
  NOT_SHAREABLE: "notShareable",
  HELD_COMMITMENTS: "heldCommitments",
  UNSPEAKABLE: "unspeakable",
  EMPTY_ANSWERS: "emptyAnswers",
  AUDIO_UNAVAILABLE: "audioUnavailable",
});

/**
 * A session's counters and how often each rule decided. The session's public counter properties
 * (session.filled, ...) read and write these, so their names and values stay as they were.
 */
class Stats {
  constructor() {
    this._counts = new Map(Object.values(COUNTER).map((counter) => [counter, 0]));
    this._rules = new Map();
  }

  get(counter) {
    return this._counts.get(counter);
  }

  set(counter, value) {
    this._counts.set(counter, value);
  }

  add(counter, amount = 1) {
    this._counts.set(counter, this._counts.get(counter) + amount);
  }

  /** One more turn or answer that `rule` decided. */
  countRule(rule) {
    this._rules.set(rule, (this._rules.get(rule) || 0) + 1);
  }

  ruleCounts() {
    return Object.fromEntries([...this._rules].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)));
  }

  /** Gives `target` one property per counter (target.filled, ...) that reads and writes this Stats. */
  static defineCounterProperties(target) {
    for (const counter of Object.values(COUNTER)) {
      Object.defineProperty(target, counter, {
        get() {
          return this._stats.get(counter);
        },
        set(value) {
          this._stats.set(counter, value);
        },
        configurable: true,
      });
    }
  }
}

module.exports = { COUNTER, Stats };
