"use strict";
const { LATE, within } = require("../runtime/deadline.js");
const { COUNTER } = require("../runtime/stats.js");
const { isContextDependent } = require("./wordRules/followUp.js");
const { isPersonal } = require("./wordRules/personal.js");

/** What the word rules make of one turn's words. Each reading is worked out once, when a rule first needs it. */
class WordReading {
  constructor(text) {
    this.text = text;
    this._read = new Map();
  }

  /** The word rules make no frame. */
  get frame() {
    return null;
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** About the caller's own records, or otherwise never shared. */
  get isPersonal() {
    return this._once("isPersonal", () => isPersonal(this.text));
  }

  /** Only means something next to the turn before it. */
  get isContextDependent() {
    return this._once("isContextDependent", () => isContextDependent(this.text));
  }
}

/**
 * The classifier a voice session uses when no understander is plugged in: the fixed word rules,
 * so nothing changes without opt-in.
 */
class WordRuleClassifier {
  classify(text, facts = []) {
    return new WordReading(text);
  }
}

/**
 * Null Object for the rewriter slot: no stand-alone question, so a turn's cache key stays the
 * caller's own words (or the chain a follow-up leans on), as today.
 */
class NoRewrite {
  rewrite() {
    return null;
  }
}

/** A turn's reading with the rewrite made inside the same budget (null: the caller's words). */
class BudgetedReading {
  constructor(reading, rewritten) {
    this.reading = reading;
    this.rewritten = rewritten;
  }

  get isPersonal() {
    return this.reading.isPersonal;
  }

  get isContextDependent() {
    return this.reading.isContextDependent;
  }

  get frame() {
    return this.reading.frame ?? null;
  }
}

/**
 * Decorator over a classifier and a rewriter that fills both slots: the model reads and rewrites a
 * turn inside `budgetMs` (null: no deadline). This is the one place understanding fails open: a late
 * or failed model means the word rules read the turn and it keeps the caller's words, never "share
 * anyway". Each such turn is counted (understandTimeouts, understandErrors) and logged without its
 * words. A late call holds no thread in Node, so unlike Python it needs no in-flight bound.
 */
class BudgetedUnderstanding {
  constructor(classifier, rewriter, { budgetMs, count, warn = (message) => console.warn(message), fallback = null }) {
    this._classifier = classifier;
    this._rewriter = rewriter;
    this._budgetMs = budgetMs;
    this._count = count;
    this._warn = warn;
    this._fallback = fallback || new WordRuleClassifier();
  }

  /** The model's reading and rewrite, or the word rules' reading when the model is late or fails. */
  async classify(text, facts = []) {
    let understood;
    try {
      const understanding = this._understand(text, facts);
      understood = this._budgetMs === null ? await understanding : await within(this._budgetMs, understanding);
    } catch (error) {
      return this._fallBack(text, COUNTER.UNDERSTAND_ERRORS, `failed (${(error && error.name) || typeof error})`);
    }
    if (understood === LATE) {
      return this._fallBack(text, COUNTER.UNDERSTAND_TIMEOUTS, `passed the ${this._budgetMs}ms budget`);
    }
    return new BudgetedReading(understood.reading, understood.rewritten);
  }

  /** The rewrite made with the reading (classify() ran both). */
  rewrite(text, reading) {
    return reading.rewritten;
  }

  async _understand(text, facts) {
    const reading = await this._classifier.classify(text, facts);
    const rewritten = await this._rewriter.rewrite(text, reading);
    return { reading, rewritten: rewritten ?? null };
  }

  _fallBack(text, counter, why) {
    this._count(counter);
    this._warn(`crowkis understanding ${why}; the word rules read this turn`);
    return new BudgetedReading(this._fallback.classify(text), null);
  }
}

module.exports = { WordReading, WordRuleClassifier, NoRewrite, BudgetedUnderstanding, BudgetedReading };
