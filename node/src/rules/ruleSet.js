"use strict";

const { FloorRuleLocked, RuleChain, UnknownRule, ruleNames } = require("./chain.js");
const {
  CommitmentRewording, ConfidenceBar, DifferentQuestion, PiiPlaceholder, ScreenOnlyAnswer, ShortTurnUnvouched,
  TemplateSlotMissing,
} = require("./hit/index.js");
const {
  CallContextTaint, CutOff, EmptyTurn, FollowUpWithoutContext, OwnRecords, PrivateChain, RegisteredFiller, TooShort,
  VoiceStatedFacts,
} = require("./question/index.js");
const {
  CallerIdentifier, DeclaredValue, EmptyAnswer, NoKey, NonAnswer, NotShareable, PersonalTemplate, PromptCallerDetails,
  TaintedCall, ToolResult, VoiceActionClaim, VoicePrivateWord,
} = require("./save/index.js");
const { CachedAnswer } = require("../turns/values.js");
const { Checked } = require("../turns/values.js");
const { Hit } = require("../turns/values.js");

const CHAINS = ["beforeFiller", "filler", "question", "hit", "answerGiven", "beforeSharing", "sharing"];

/**
 * The rules of the three SDK stages, as chains in the order a turn meets them. Stage 1
 * (question) runs `beforeFiller`, then `filler` (a registered filler answers the turn itself), then
 * `question`. Stage 2
 * (hit) runs `hit` on a hit. Stage 3 (save) runs `answerGiven`, then `beforeSharing` once the
 * turn is in the transcript, then `personal` for a personal turn (whose answer may become a
 * shared shape) or `sharing` for any other. Immutable.
 *
 * The set is also TurnCore's question and hit check for a voice call (checkQuestion, checkHit): those
 * two stages are only its rules.
 */
class RuleSet {
  constructor({ beforeFiller, filler, question, hit, answerGiven, beforeSharing, personal, sharing }) {
    Object.assign(this, { beforeFiller, filler, question, hit, answerGiven, beforeSharing, personal, sharing });
    Object.freeze(this);
  }

  /** The voice defaults: today's rules, in today's order; `fillers` is the session's live Map of registered fillers. */
  static voice(fillers = new Map()) {
    return new RuleSet({
      beforeFiller: new RuleChain([new EmptyTurn()]),
      filler: new RuleChain([new RegisteredFiller({ fillers })]),
      question: new RuleChain([new CallContextTaint(), new TooShort(), new CutOff(), new OwnRecords(),
        new FollowUpWithoutContext(), new PrivateChain()]),
      hit: new RuleChain([new ConfidenceBar(), new TemplateSlotMissing(), new PiiPlaceholder(), new DifferentQuestion(),
        new ShortTurnUnvouched(), new CommitmentRewording(), new ScreenOnlyAnswer()]),
      answerGiven: new RuleChain([new EmptyAnswer()]),
      beforeSharing: new RuleChain([new NoKey(), new ToolResult(), new PromptCallerDetails()]),
      personal: new PersonalTemplate(),
      sharing: new RuleChain([new TaintedCall(), new NotShareable(), new DeclaredValue(), new CallerIdentifier(),
        new VoicePrivateWord(), new VoiceActionClaim(), new NonAnswer()]),
    });
  }

  /**
   * The rules of a voice session with an understander plugged in (v4): StatedFacts, which keeps only
   * the turns whose answer a stated fact may change, replaces the call-wide CallContextTaint, and the save
   * check is the same as without one.
   */
  static understood(fillers = new Map()) {
    const rules = RuleSet.voice(fillers);
    return new RuleSet({ ...rules, question: rules.question.replacing("CallContextTaint", new VoiceStatedFacts()) });
  }

  /**
   * Stage 1: the first objection of `beforeFiller`, `filler` (a filler answers the turn itself), then
   * `question`. As a chain answers, the objection may still be pending (TurnCore awaits it).
   */
  checkQuestion(turn) {
    return this._firstObjection(turn, [this.beforeFiller, this.filler, this.question]);
  }

  /** Stage 2: the hit as the hit rules read it, and their first objection (it may still be pending). */
  checkHit(turn, hit, started) {
    const cached = new CachedAnswer(turn, Hit.fromAgent(hit), started);
    return new Checked(cached, this.hit.firstObjection(cached));
  }

  // The first objection of `chains`, in order. The last chain's may stay pending; an earlier one's is
  // awaited first, since whether the next chain runs depends on it.
  _firstObjection(turn, chains) {
    const [chain, ...rest] = chains;
    const verdict = chain.firstObjection(turn);
    if (RuleChain.isPending(verdict) && rest.length) {
      return verdict.then((found) => (found ? new Checked(turn, found) : this._firstObjection(turn, rest)));
    }
    if (verdict || !rest.length) return new Checked(turn, verdict || null);
    return this._firstObjection(turn, rest);
  }

  /**
   * These rules with the named ones turned off; a floor rule stays on unless `unsafe`. The
   * personal-answer rule is never turned off: it decides when an answer about the caller's own
   * records is shared. A name the set does not have is refused.
   */
  without(names, { unsafe = false } = {}) {
    ruleNames(names);
    const known = new Set([...CHAINS.flatMap((chain) => this[chain].names), this.personal.name]);
    const unknown = names.filter((name) => !known.has(name));
    if (unknown.length) throw new UnknownRule(`no such rule: ${unknown.join(", ")}`);
    if (names.includes(this.personal.name)) {
      throw new FloorRuleLocked(`${this.personal.name} cannot be turned off: it decides when an answer about ` +
        "the caller's own records is shared");
    }
    const chains = Object.fromEntries(CHAINS.map((chain) => [chain, this[chain].without(names, { unsafe })]));
    return new RuleSet({ ...chains, personal: this.personal });
  }
}

module.exports = { RuleSet };
