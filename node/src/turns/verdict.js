"use strict";

/**
 * What a rule says when it objects. `rule` names the rule (in decisions, logs and stats()),
 * `reason` says why in words, `counts` are the session counters it adds to, `outcome` is, for a
 * save rule, what happened to the answer (an OUTCOME; Chat's refusal adds its reason:
 * `because(OUTCOME.REFUSED, why)`), and `route` is, for a Chat
 * rule that decides alone, where the turn goes ("urgent", "task", "filler"), and `answer` is what to
 * say at once when the rule answers the turn itself (a filler). Immutable.
 */
class Verdict {
  /**
   * @param {string} rule
   * @param {string} reason
   * @param {string[]} [counts]
   * @param {string|null} [outcome]
   * @param {string|null} [route]
   * @param {string|null} [answer]
   */
  constructor(rule, reason, counts = [], outcome = null, route = null, answer = null) {
    this.rule = rule;
    this.reason = reason;
    this.counts = Object.freeze([...counts]);
    this.outcome = outcome;
    this.route = route;
    this.answer = answer;
    Object.freeze(this);
  }
}

module.exports = { Verdict };
