"use strict";

const { RuleChain, UnknownRule, ruleNames } = require("./chain.js");
const {
  AboutSomeone, IdentifyingDetails, LostDetail, NoQuestion, NotGeneral, StatedFacts, TaskStep, UncertainFrame, Ungrounded,
  UnresolvedReference, UrgentTurn,
} = require("./question/index.js");

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
