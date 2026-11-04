"use strict";

const { CachedAnswer } = require("./cachedAnswer.js");
const { Checked } = require("./checked.js");
const { CACHE_ROUTE, Hit } = require("./hit.js");
const { Verdict } = require("./verdict.js");

// A miss, or a hit below the bar: the model answers; not counted.
const NOT_CONFIDENT = new Verdict("NotConfident", "no confident cached answer");
// Chat speaks a cached commitment (a price, a refund, a policy) only for the exact same question (decision V2).
const CHAT_COMMITMENTS = "exact";

/** A hit rule's refusal, counted under the rule's name; null when no rule refused. */
function counted(objection) {
  return objection ? new Verdict(objection.rule, objection.reason, [objection.rule]) : null;
}

/** Adapter: the call a chat hit belongs to, as the hit rules read it (the SessionCall of voice, hit side). */
class ChatHitCall {
  constructor(records, budgetMs) {
    this._records = records;
    this._budgetMs = budgetMs;
  }

  get commitments() {
    return CHAT_COMMITMENTS;
  }

  /** Every question the cached answer was saved for asks about something else (read within what the lookup left of the budget). */
  answersAnotherQuestion(asked, answer, spentMs) {
    const budgeted = this._budgetMs !== null && this._budgetMs !== undefined;
    return this._records.answersAnotherQuestion(asked, answer, budgeted ? this._budgetMs - spentMs : null);
  }
}

/** The shared question a chat hit answers, as the hit rules read the turn: never personal (only a shared question is looked up). */
class ChatHitTurn {
  constructor(key, call) {
    this.key = key;
    this.call = call;
  }

  get isPersonal() {
    return false;
  }
}

/**
 * A confident hit with an answer is checked by the hit rules (`hitRules`, reading the questions each
 * answer was saved for within what the lookup left of the budget); a refusal is counted under the
 * rule's name. Not voice's check (RuleSet.checkHit): a chat stops an unconfident hit before its rules
 * and uncounted, and counts a refusal by the rule's name. `session` is read live (latencyBudgetMs).
 */
class ChatHitCheck {
  constructor(session, { hitRules, questionRecords }) {
    this._session = session;
    this._hitRules = hitRules;
    this._questionRecords = questionRecords;
  }

  checkHit(turn, hit, started) {
    if (!(hit && hit.route === CACHE_ROUTE && hit.answer)) return new Checked(null, NOT_CONFIDENT);
    const call = new ChatHitCall(this._questionRecords, this._session.latencyBudgetMs);
    const cached = new CachedAnswer(new ChatHitTurn(turn.key, call), Hit.fromAgent(hit), started);
    // The hit rules' word is a promise even when they answer at once, as Chat always awaited it.
    return new Checked(cached, Promise.resolve(this._hitRules.firstObjection(cached)).then(counted));
  }
}

module.exports = { CHAT_COMMITMENTS, ChatHitCall, ChatHitCheck, ChatHitTurn };
