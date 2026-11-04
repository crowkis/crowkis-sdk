"use strict";

// Chat's question check and hit check, the twin of rules/ruleSet.js's voice checks.

const { Verdict: ChatVerdict } = require("../../rules/ruleChecker.js");
const { privateWords } = require("../../understanding/wordRules/chat.js");
const { statedNames } = require("../../understanding/wordRules/personal.js");
const { AGENT, URGENT } = require("../results.js");
const { CACHE_ROUTE, CachedAnswer, Checked, Hit, Verdict } = require("../values.js");
const { ChatTurn } = require("./turn.js");

const CHECK_RULE = "ChatQuestionCheck";

/**
 * The rule checker (V1-V10, every objection reported) keys a shareable question; then, on what the
 * chat has learnt, the shared-question rules may still keep it with the agent, and the fixed urgent
 * words send a turn about the user to the urgent route whatever the model said. The chat's state
 * takes the turn in, and its route is counted. A shared question is remembered by the safe fallback;
 * any other route is the objection (the model answers with the whole chat). `session` is read live
 * (state, counts, checker, replay).
 */
class ChatQuestionCheck {
  constructor(session, { sharedQuestionRules, urgentWords }) {
    this._session = session;
    this._sharedQuestionRules = sharedQuestionRules;
    this._urgentWords = urgentWords;
  }

  checkQuestion(reading) {
    const verdict = this._verdict(reading);
    const state = this._session.state;
    state.apply(reading.frame, { shared: verdict.shared });
    // A turn that is not telling a fact may still give a name ("hi i'm sarah"); a fact turn keeps
    // its words ("I'm allergic"), since the shared question must carry them.
    state.notePrivate([...(verdict.shared ? [] : privateWords(reading.text, reading.frame)), ...reading.names,
      ...statedNames([reading.text])]); // lower-case too: only answers are checked against these
    this._session.counts[verdict.route] += 1;
    const checked = reading.checkedAs(verdict);
    if (!verdict.shared) return new Checked(checked, new Verdict(CHECK_RULE, verdict.reasons.join(";"), [], null, verdict.route));
    if (this._session.replay) this._session.replay.remember(reading.text, verdict.question, reading.frame.questionType);
    return new Checked(checked);
  }

  _verdict(reading) {
    const state = this._session.state;
    let verdict = this._session.checker.check(reading.frame, reading.text, state);
    const chatTurn = new ChatTurn(reading.frame, reading.text, state);
    if (verdict.shared) {
      const objection = this._sharedQuestionRules.firstObjection(chatTurn);
      if (objection) verdict = new ChatVerdict(false, AGENT, [objection.reason]);
    }
    if (verdict.route !== URGENT && reading.aboutCaller) {
      const objection = this._urgentWords.check(chatTurn);
      if (objection) verdict = new ChatVerdict(false, objection.route, [objection.reason]); // never left to the model alone
    }
    return verdict;
  }
}

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

module.exports = { CHAT_COMMITMENTS, ChatHitCall, ChatHitCheck, ChatHitTurn, ChatQuestionCheck };
