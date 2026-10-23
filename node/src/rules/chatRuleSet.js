"use strict";

const { RuleChain, UnknownRule, ruleNames } = require("./chain.js");
const { CommitmentRewording, DifferentQuestion, PiiPlaceholder } = require("./hit/index.js");
const {
  AboutSomeone, IdentifyingDetails, LostDetail, NoQuestion, NotGeneral, QuestionNamesCaller, StatedFacts, TaskStep,
  ToldDetailDropped, UncertainFrame, Ungrounded, UnresolvedReference, UntaggedName, UrgentTurn,
} = require("./question/index.js");
const {
  ActionClaim, AttributeNotInKey, ChatEmptyAnswer, ChatNonAnswer, ChatPromptDetails, IdentifyingAnswer, PrivateWord,
} = require("./save/index.js");

const V7 = "V7_LostOrDropped";
const CHAINS = ["decisive", "frame", "question"];

/**
 * Chat's question rules (V1-V10), in the three groups the rule checker runs: `decisive` (the first
 * objection decides alone and names the route: urgent, a task step), `frame` (every objection is
 * reported; the frame is not a general question) and `question` (every objection is reported; the
 * stand-alone question is not safe as a key). Within `question`, V7 is one objection: a lost detail
 * of this turn, else a dropped fact the caller stated. Immutable.
 */
class ChatRuleSet {
  constructor({ decisive, frame, question }) {
    Object.assign(this, { decisive, frame, question });
    Object.freeze(this);
  }

  /**
   * The checks a session runs once the rule checker would share a question, on what the chat has
   * learnt (names, told details): the first objection keeps the turn with the agent.
   */
  static sharedQuestionChain() {
    return new RuleChain([new QuestionNamesCaller(), new ToldDetailDropped(), new UntaggedName()]);
  }

  /**
   * The hit guards every channel runs (v4): a placeholder for someone's detail, an answer saved for a
   * different question, a commitment for anything but the exact same question.
   */
  static hitChain() {
    return new RuleChain([new PiiPlaceholder(), new DifferentQuestion(), new CommitmentRewording()]);
  }

  /**
   * Chat's save rules, in saveCheck's order: the first objection is why an answer to a shared
   * question is not saved.
   */
  static saveChain() {
    return new RuleChain([new ChatEmptyAnswer(), new ChatNonAnswer(), new IdentifyingAnswer(), new ActionClaim(),
      new AttributeNotInKey(), new PrivateWord(), new ChatPromptDetails()]);
  }

  /** Chat's rules today, in today's order. */
  static chat(confidenceFloor) {
    return new ChatRuleSet({
      decisive: new RuleChain([new UrgentTurn(), new TaskStep()]),
      frame: new RuleChain([new UncertainFrame({ confidenceFloor }), new NotGeneral(), new AboutSomeone(), new NoQuestion()]),
      question: new RuleChain([new IdentifyingDetails(), new Ungrounded(), new UnresolvedReference(),
        new RuleChain([new LostDetail(), new StatedFacts()], { name: V7 })]),
    });
  }

  /** These rules with the named ones turned off; a floor rule stays on unless `unsafe`. */
  without(names, { unsafe = false } = {}) {
    ruleNames(names);
    const known = new Set(CHAINS.flatMap((chain) => this[chain].allNames));
    const unknown = names.filter((name) => !known.has(name));
    if (unknown.length) throw new UnknownRule(`no such rule: ${unknown.join(", ")}`);
    return new ChatRuleSet(Object.fromEntries(CHAINS.map((chain) => [chain, this[chain].without(names, { unsafe })])));
  }
}

module.exports = { ChatRuleSet };
