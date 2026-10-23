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

const CHAINS = ["beforeFiller", "filler", "question", "hit", "answerGiven", "beforeSharing", "sharing"];

/**
 * The rules of the three SDK stages, as chains in the order a turn meets them. Stage 1
 * (question) runs `beforeFiller`, then `filler` (a registered filler answers the turn itself), then
 * `question`. Stage 2
 * (hit) runs `hit` on a hit. Stage 3 (save) runs `answerGiven`, then `beforeSharing` once the
 * turn is in the transcript, then `personal` for a personal turn (whose answer may become a
 * shared shape) or `sharing` for any other. Immutable.
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
        new NonAnswer()]),
    });
  }

  /**
   * The rules of a voice session with an understander plugged in (v4): StatedFacts, which keeps only
   * the turns whose answer a stated fact may change, replaces the call-wide CallContextTaint, and the save
   * check gains Chat's PrivateWord and ActionClaim (the merged save check).
   */
  static understood(fillers = new Map()) {
    const rules = RuleSet.voice(fillers);
    const sharing = new RuleChain([new TaintedCall(), new NotShareable(), new DeclaredValue(), new CallerIdentifier(),
      new VoicePrivateWord(), new VoiceActionClaim(), new NonAnswer()]);
    return new RuleSet({ ...rules, question: rules.question.replacing("CallContextTaint", new VoiceStatedFacts()), sharing });
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
