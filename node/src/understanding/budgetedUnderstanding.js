"use strict";

const { LATE, within } = require("../runtime/deadline.js");
const { COUNTER } = require("../runtime/stats.js");
const { WordRuleClassifier } = require("./wordRuleClassifier.js");

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
  async classify(text) {
    let understood;
    try {
      const understanding = this._understand(text);
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

  async _understand(text) {
    const reading = await this._classifier.classify(text);
    const rewritten = await this._rewriter.rewrite(text, reading);
    return { reading, rewritten: rewritten ?? null };
  }

  _fallBack(text, counter, why) {
    this._count(counter);
    this._warn(`crowkis understanding ${why}; the word rules read this turn`);
    return new BudgetedReading(this._fallback.classify(text), null);
  }
}

module.exports = { BudgetedUnderstanding, BudgetedReading };
