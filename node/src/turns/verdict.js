"use strict";

/**
 * What a rule says when it objects. `rule` names the rule (in decisions, logs and stats()),
 * `reason` says why in words, `counts` are the session counters it adds to, `outcome` is, for a
 * save rule, what happened to the answer ("kept", "private", ...), and `route` is, for a Chat
 * question rule that decides alone, where the turn goes ("urgent", "task"). Immutable.
 */
class Verdict {
  /**
   * @param {string} rule
   * @param {string} reason
   * @param {string[]} [counts]
   * @param {string|null} [outcome]
   * @param {string|null} [route]
   */
  constructor(rule, reason, counts = [], outcome = null, route = null) {
    this.rule = rule;
    this.reason = reason;
    this.counts = Object.freeze([...counts]);
    this.outcome = outcome;
    this.route = route;
    Object.freeze(this);
  }
}

module.exports = { Verdict };
