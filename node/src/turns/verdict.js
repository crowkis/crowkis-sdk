"use strict";

/**
 * What a rule says when it objects. `rule` names the rule (in decisions, logs and stats()),
 * `reason` says why in words, `counts` are the session counters it adds to, and `outcome` is,
 * for a save rule, what happened to the answer ("kept", "private", ...). Immutable.
 */
class Verdict {
  /**
   * @param {string} rule
   * @param {string} reason
   * @param {string[]} [counts]
   * @param {string|null} [outcome]
   */
  constructor(rule, reason, counts = [], outcome = null) {
    this.rule = rule;
    this.reason = reason;
    this.counts = Object.freeze([...counts]);
    this.outcome = outcome;
    Object.freeze(this);
  }
}

module.exports = { Verdict };
