"use strict";

// SessionCall: what a voice call knows, as the rules and steps read it.

const { followUpKey } = require("../../keys/knowledgeSegment.js");
const { LATE, within } = require("../../runtime/deadline.js");
const { QuestionRecords } = require("../../runtime/questionRecords.js");
const { isContextDependent } = require("../../understanding/wordRules/followUp.js");
const { identifiers, isPersonal } = require("../../understanding/wordRules/personal.js");
const { FOLLOW_UP_WORDS, URGENT, wordsOf } = require("../../understanding/wordRules/text.js");
const { urgent } = require("../../understanding/wordRules/urgent.js");

// How many follow-ups back a turn may lean on before it is treated as unresolvable.
const CHAIN_LIMIT = 6;

/**
 * A voice call as its rules and turn steps see it (SessionCall). The session's settings
 * are read live (an app may change them between turns); what the call works out from what it has
 * heard is done here: the earlier turns a follow-up leans on (chain), a turn's cache key, a turn
 * after an urgent one, the IDs the caller said before, whose system prompts it is compared with, and
 * whether the server vouches for what it caches (asked inside the budget). The session's `state`
 * remembers how each turn was read; `track` is told of each question record still being written. The one
 * change a rule makes is markTainted().
 */
class SessionCall {
  constructor(session, { track }) {
    this._session = session;
    this._track = track;
  }

  get channel() {
    return this._session.channel;
  }

  get tainted() {
    return this._session.state.tainted;
  }

  get values() {
    return this._session.values;
  }

  get hasValues() {
    return Object.keys(this._session.values).length > 0;
  }

  get minWords() {
    return this._session.minWords;
  }

  get shortTurns() {
    return this._session.shortTurns;
  }

  get serveAbove() {
    return this._session.serveAbove;
  }

  get commitments() {
    return this._session.commitments;
  }

  isPersonal(text) {
    return this._session.state.isPersonal(text);
  }

  isContextDependent(text) {
    return this._session.state.isContextDependent(text);
  }

  stated() {
    return [...this._session.state.stated];
  }

  facts() {
    return [...this._session.state.facts];
  }

  markPrivate(text) {
    this._session.state.markPrivate(text);
  }

  privateWords() {
    return new Set(this._session.state.privateRaw);
  }

  markTainted() {
    this._session.state.tainted = true;
  }

  /**
   * Whether the server judges what it caches, asked inside this call's budget:
   * a slow answer is a no for this turn, and is there for the next.
   */
  async engineVouches() {
    const asked = this._session.agent.decides();
    const budgetMs = this._session.latencyBudgetMs;
    if (budgetMs === undefined || budgetMs === null) return asked;
    const answer = await within(budgetMs, asked);
    return answer === LATE ? false : answer;
  }

  /**
   * The earlier caller turns a follow-up leans on, oldest first: back to the latest one that stands on
   * its own. null when there is no such turn.
   */
  chain() {
    const transcript = this._session.transcript;
    const chain = [];
    for (let index = transcript.length - 1; index >= 0; index -= 1) {
      const turn = transcript[index];
      if (turn.role !== "user") continue;
      chain.unshift(turn.content);
      if (!isContextDependent(typeof turn.content === "string" ? turn.content.trim() : "")) return chain;
      if (chain.length >= CHAIN_LIMIT) return null;
    }
    return null;
  }

  /**
   * A short turn after a private emergency or medical turn ("is he going to be okay?", "how do i make
   * her vomit?"): about that turn, so answered with the call.
   */
  afterUrgent(text) {
    if (wordsOf(text).length > FOLLOW_UP_WORDS) return false;
    const earlier = this._session.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    for (const said of earlier.slice(-CHAIN_LIMIT).reverse()) {
      const words = wordsOf(said);
      if ((words.some((w) => URGENT.has(w)) || urgent(words)) && isPersonal(said)) return true;
      if (words.length > FOLLOW_UP_WORDS) return false;
    }
    return false;
  }

  /** The cache key of a turn: its words, or its chain for a follow-up; null without one. */
  contextKey(said, text) {
    if (!this._session.state.isContextDependent(text)) return followUpKey(said);
    const chain = this.chain();
    return chain === null ? null : followUpKey(said, chain);
  }

  /**
   * Whether every question this answer was saved for asks about something else, read within what the
   * lookup left of the budget. Unknown means no: as before.
   */
  async answersAnotherQuestion(asked, answer, spentMs = 0) {
    const budgetMs = this._session.latencyBudgetMs;
    const budgeted = budgetMs !== undefined && budgetMs !== null;
    return this.questionRecords().answersAnotherQuestion(asked, answer, budgeted ? budgetMs - spentMs : null);
  }

  /**
   * The ID-like values this caller said earlier in the call: its earlier turns in the transcript and
   * the turns the session only heard (private turns, loaded history). Called once the turn being
   * recorded is in the transcript, so that turn is left out: it passed the personal rules, so its
   * numbers are not private.
   */
  saidIdentifiers() {
    const said = this._session.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content).slice(0, -1);
    return identifiers([...said, ...[...this._session.state.heard].sort()]);
  }

  /** Which agent's system prompts this call's is compared with. */
  agentKey() {
    const agent = this._session.agent || {};
    return [agent.tenant || (agent.client && agent.client.tenant) || null, agent.agentId || null];
  }

  /** Which questions each shared answer was saved for, through the session's agent of now. */
  questionRecords() {
    return new QuestionRecords(this._session.agent, { track: this._track });
  }
}

module.exports = { CHAIN_LIMIT, SessionCall };
