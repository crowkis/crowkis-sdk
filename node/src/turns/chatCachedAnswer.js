"use strict";

// Chat speaks a cached commitment (a price, a refund, a policy) only for the exact same question (decision V2).
const CHAT_COMMITMENTS = "exact";

/** Adapter: the call a Chat hit belongs to, as the hit rules read it (the voice VoiceCall's hit side). */
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

/** The shared question a Chat hit answers: never personal (only a shared question is looked up). */
class ChatHitTurn {
  constructor(key, call) {
    this.key = key;
    this.call = call;
  }

  get isPersonal() {
    return false;
  }
}

/** What the cache returned for a Chat question. `started` is when the lookup began (performance.now()). */
class ChatCachedAnswer {
  constructor(turn, hit, started) {
    this.turn = turn;
    this.hit = hit;
    this.started = started;
  }

  get answer() {
    return this.hit.answer;
  }
}

module.exports = { CHAT_COMMITMENTS, ChatCachedAnswer, ChatHitCall, ChatHitTurn };
