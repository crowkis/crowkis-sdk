"use strict";

// The StatedFacts rule for voice with an understander (stage 1, question).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");
const { FactRelevanceCheck } = require("../../understanding/factRelevance.js");
const { setsContext } = require("../../understanding/wordRules/index.js");
const { unnamed } = require("../../understanding/chatDetails.js");

const TELLS_REASON = "the turn tells the call something a later answer may depend on; its own answer stays with this caller";
const DEPENDS_REASON =
  "the caller told this call something that may change this answer (or the model could not say it does " +
  "not); a shared answer to the bare question could be wrong for them";

// The model was sent this stated turn with a number or a content word masked ("flying to _ with _
// bags"), so it judged the turn without it: the turn counts.
function hidden(stated, privateWords) {
  const stems = FactRelevanceCheck._contentStems;
  const kept = stems(unnamed(stated, privateWords));
  return /\p{Nd}/u.test(stated) || [...stems(stated)].some((s) => !kept.has(s));
}

/**
 * Replaces CallContextTaint when an understander is plugged in: a turn that tells the call something
 * (a condition, an age, a plan) stays private, and so does each later turn unless the model is sure
 * that none of the stated facts changes its answer and none is an allergy, a medication, a pregnancy
 * or an age. Unsure, late or failed: private, as before. Instead of tainting the call, it keeps just
 * that turn private (markPrivate).
 */
class VoiceStatedFacts {
  constructor({ relevance = new FactRelevanceCheck() } = {}) {
    this._relevance = relevance;
  }

  get name() {
    return "VoiceStatedFacts";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (setsContext(turn.text)) return this._private(turn, TELLS_REASON);
    // The call heard something its model never read (loaded history, a private turn).
    if (turn.call.tainted) return this._private(turn, DEPENDS_REASON);
    const privateWords = turn.call.privateWords();
    if (turn.call.stated().some((stated) => hidden(stated, privateWords) || !this._relevance.irrelevant(stated, turn.frame))) {
      return this._private(turn, DEPENDS_REASON);
    }
    return null;
  }

  _private(turn, reason) {
    turn.call.markPrivate(turn.text);
    return new Verdict(this.name, reason, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

module.exports = { VoiceStatedFacts };
