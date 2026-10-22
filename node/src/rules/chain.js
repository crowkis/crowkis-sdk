"use strict";

/** A floor rule was asked to be turned off without the explicit unsafe flag. */
class FloorRuleLocked extends require("../../index.js").CrowkisError {
  constructor(message) {
    super(message);
    this.name = "FloorRuleLocked";
  }
}

/**
 * Chain of Responsibility: the rules of one stage, run in order; the first objection wins and
 * names its rule. A rule has a `name`, a `floor` flag and a `check(subject)` that returns a
 * Verdict, or null when it has no objection (or a promise of either).
 */
class RuleChain {
  constructor(rules) {
    this._rules = Object.freeze([...rules]);
  }

  get names() {
    return this._rules.map((rule) => rule.name);
  }

  /** The first rule's objection to `subject`, or null when every rule lets it through. */
  async firstObjection(subject) {
    for (const rule of this._rules) {
      const verdict = await rule.check(subject);
      if (verdict) return verdict;
    }
    return null;
  }

  /** This chain with the named rules turned off. A floor rule stays on unless `unsafe`. */
  without(names, { unsafe = false } = {}) {
    const locked = this._rules.filter((rule) => names.includes(rule.name) && rule.floor).map((rule) => rule.name);
    if (locked.length && !unsafe) {
      throw new FloorRuleLocked(`floor rules cannot be turned off without unsafe: true: ${locked.join(", ")}`);
    }
    return new RuleChain(this._rules.filter((rule) => !names.includes(rule.name)));
  }
}

module.exports = { FloorRuleLocked, RuleChain };
