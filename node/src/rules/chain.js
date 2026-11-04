"use strict";

/** A floor rule was asked to be turned off without the explicit unsafe flag. */
class FloorRuleLocked extends require("../client/connection.js").CrowkisError {
  constructor(message) {
    super(message);
    this.name = "FloorRuleLocked";
  }
}

/** A rule was named that the rule set does not have. */
class UnknownRule extends require("../client/connection.js").CrowkisError {
  constructor(message) {
    super(message);
    this.name = "UnknownRule";
  }
}

/** The names as an array; one string is refused, as it would match by its letters. */
function ruleNames(names) {
  if (!Array.isArray(names)) throw new TypeError("rule names are an array of names, not one string");
  return names;
}

const isPending = (value) => Boolean(value) && typeof value.then === "function";

/**
 * Chain of Responsibility: the rules of one stage, run in order; the first objection wins and
 * names its rule. A rule has a `name`, a `floor` flag and a `check(subject)` that returns a
 * Verdict, or null when it has no objection, or a promise of either when it must ask the
 * server. The chain stays synchronous until a rule returns a promise, so a session's steps run
 * without a break, as they did before the chains.
 */
class RuleChain {
  constructor(rules, { name = "", floor = false } = {}) {
    this._rules = Object.freeze([...rules]);
    this.name = name;
    this.floor = floor;
  }

  get names() {
    return this._rules.map((rule) => rule.name);
  }

  /**
   * The first rule's objection to `subject`, or null when every rule lets it through: at once,
   * or as a promise once a rule had to ask the server (see RuleChain.isPending).
   */
  firstObjection(subject) {
    for (let index = 0; index < this._rules.length; index += 1) {
      const verdict = this._rules[index].check(subject);
      if (isPending(verdict)) return this._settle(verdict, subject, index + 1);
      if (verdict) return verdict;
    }
    return null;
  }

  async _settle(pending, subject, next) {
    const verdict = await pending;
    if (verdict) return verdict;
    for (const rule of this._rules.slice(next)) {
      const later = await rule.check(subject);
      if (later) return later;
    }
    return null;
  }

  /** This chain as one rule (Composite): its first objection. */
  check(subject) {
    return this.firstObjection(subject);
  }

  /** A floor rule, or a chain with a floor rule anywhere inside it. */
  static _holdsFloor(rule) {
    return Boolean(rule.floor) || (rule instanceof RuleChain && rule._rules.some((inner) => RuleChain._holdsFloor(inner)));
  }

  /** Every rule's objection to `subject`, in order. Chat's rules answer at once; one that does not is refused. */
  allObjections(subject) {
    const found = [];
    for (const rule of this._rules) {
      const verdict = rule.check(subject);
      if (isPending(verdict)) throw new TypeError(`${rule.name} answered with a promise; allObjections needs answers at once`);
      if (verdict) found.push(verdict);
    }
    return found;
  }

  /** Every rule's name, the rules of chains inside this one included. */
  get allNames() {
    return this._rules.flatMap((rule) => (rule instanceof RuleChain ? [rule.name, ...rule.allNames] : [rule.name]));
  }

  /** Whether firstObjection() gave a promise rather than its answer. */
  static isPending(value) {
    return isPending(value);
  }

  /** This chain with the named rules turned off. A floor rule stays on unless `unsafe`. */
  without(names, { unsafe = false } = {}) {
    ruleNames(names);
    const locked = this._rules.filter((rule) => names.includes(rule.name) && RuleChain._holdsFloor(rule)).map((rule) => rule.name);
    if (locked.length && !unsafe) {
      throw new FloorRuleLocked(`floor rules cannot be turned off without unsafe: true: ${locked.join(", ")}`);
    }
    const kept = this._rules.filter((rule) => !names.includes(rule.name))
      .map((rule) => (rule instanceof RuleChain ? rule.without(names, { unsafe }) : rule));
    return new RuleChain(kept, { name: this.name, floor: this.floor });
  }

  /**
   * This chain with the rule called `name` swapped for `rule`, in the same place. A floor rule is
   * never swapped; a name the chain does not have is refused.
   */
  replacing(name, rule) {
    if (!this.names.includes(name)) throw new UnknownRule(`no such rule: ${name}`);
    if (this._rules.some((old) => old.name === name && RuleChain._holdsFloor(old))) {
      throw new FloorRuleLocked(`a floor rule cannot be replaced: ${name}`);
    }
    return new RuleChain(this._rules.map((old) => (old.name === name ? rule : old)), { name: this.name, floor: this.floor });
  }
}

module.exports = { FloorRuleLocked, RuleChain, UnknownRule, ruleNames };
