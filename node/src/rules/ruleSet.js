"use strict";

const { RuleChain } = require("./chain.js");
const {
  CommitmentRewording, ConfidenceBar, DifferentQuestion, PiiPlaceholder, ScreenOnlyAnswer, ShortTurnUnvouched,
  TemplateSlotMissing,
} = require("./hit/guards.js");
const { OwnRecords } = require("./question/floor.js");
const { FollowUpWithoutContext } = require("./question/followUp.js");
const { EmptyTurn } = require("./question/operational.js");
const { CutOff, TooShort } = require("./question/policy.js");
const { CallContextTaint, PrivateChain } = require("./question/privacy.js");
const {
  CallerIdentifier, DeclaredValue, EmptyAnswer, NoKey, NonAnswer, NotShareable, PersonalTemplate, PromptCallerDetails,
  TaintedCall, ToolResult,
} = require("./save/answer.js");

const CHAINS = ["beforeFiller", "question", "hit", "answerGiven", "beforeSharing", "sharing"];

/**
 * The rules of the three SDK stages, as chains in the order a turn meets them. Stage 1
 * (question) runs `beforeFiller` and then `question`, around the registered fillers. Stage 2
 * (hit) runs `hit` on a hit. Stage 3 (save) runs `answerGiven`, then `beforeSharing` once the
 * turn is in the transcript, then `personal` for a personal turn (whose answer may become a
 * shared shape) or `sharing` for any other. Immutable.
 */
class RuleSet {
  constructor({ beforeFiller, question, hit, answerGiven, beforeSharing, personal, sharing }) {
    Object.assign(this, { beforeFiller, question, hit, answerGiven, beforeSharing, personal, sharing });
    Object.freeze(this);
  }

  /** The voice defaults: today's rules, in today's order. */
  static voice() {
    return new RuleSet({
      beforeFiller: new RuleChain([new EmptyTurn()]),
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

  /** These rules with the named ones turned off; a floor rule stays on unless `unsafe`. */
  without(names, { unsafe = false } = {}) {
    const chains = Object.fromEntries(CHAINS.map((chain) => [chain, this[chain].without(names, { unsafe })]));
    return new RuleSet({ ...chains, personal: this.personal });
  }
}

module.exports = { RuleSet };
