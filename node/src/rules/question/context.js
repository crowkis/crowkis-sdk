"use strict";

// Stage 1 rules (question): what the call said before (a private chain, a follow-up, a reference, stated facts).

const { Verdict } = require("../../turns/values.js");
const { setsContext } = require("../../understanding/wordRules/callContext.js");
const { privateChain } = require("../../understanding/wordRules/followUp.js");
const { COUNTER } = require("../../runtime/stats.js");
const { unnamed } = require("../../understanding/wordRules/privateWords.js");
const { contentStems, statedFactIrrelevant } = require("../../understanding/model/checks.js");

const PRIVATE_CHAIN_REASON =
  "a follow-up to a private turn of this call: its answer depends on what " +
  "this caller said, so it is never answered from a shared cache";

/**
 * A follow-up to a private turn of the call, or any turn after an urgent one, is private: its
 * answer depends on what this caller said.
 */
class PrivateChain {
  get name() {
    return "PrivateChain";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const chain = turn.call.chain() || [];
    const followsPrivate = turn.isContextDependent &&
      (privateChain(chain, turn.call.minWords) || chain.some((earlier) => turn.call.isPersonal(earlier)));
    if (!(followsPrivate || turn.call.afterUrgent(turn.text))) return null;
    return new Verdict(this.name, PRIVATE_CHAIN_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

const NO_KEY_REASON =
  "the utterance only has meaning against an earlier turn and this call " +
  "has none, so no cache key can be built for it";

/** A follow-up ("and what about that") with no earlier turn to lean on has no cache key. */
class FollowUpWithoutContext {
  get name() {
    return "FollowUpWithoutContext";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.key !== null) return null;
    return new Verdict(this.name, NO_KEY_REASON, [COUNTER.INFERRED]);
  }
}

const TAINTED_REASON =
  "the caller has told this call something a later answer may depend on " +
  "(a condition, an age, a plan, an instruction, a step in their own task); " +
  "a shared answer to the bare question could be wrong for them";

/**
 * Once the caller tells the call something a later answer may depend on (a condition, an age,
 * a plan, an instruction), every later turn of the call is private. The voice default until an
 * understander can tell which stated facts change an answer.
 */
class CallContextTaint {
  get name() {
    return "CallContextTaint";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!(turn.call.tainted || setsContext(turn.text))) return null;
    turn.call.markTainted();
    return new Verdict(this.name, TAINTED_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

// The StatedFacts rule for voice with an understander (stage 1, question).
const TELLS_REASON = "the turn tells the call something a later answer may depend on; its own answer stays with this caller";
const DEPENDS_REASON =
  "the caller told this call something that may change this answer (or the model could not say it does " +
  "not); a shared answer to the bare question could be wrong for them";

// The model was sent this stated turn with a number or a content word masked ("flying to _ with _
// bags"), so it judged the turn without it: the turn counts.
function hidden(stated, privateWords) {
  const kept = contentStems(unnamed(stated, privateWords));
  return /\p{Nd}/u.test(stated) || [...contentStems(stated)].some((s) => !kept.has(s));
}

/**
 * Replaces CallContextTaint when an understander is plugged in: a turn that tells the call something
 * (a condition, an age, a plan) stays private, and so does each later turn unless the model is sure
 * that none of the stated facts changes its answer and none is an allergy, a medication, a pregnancy
 * or an age. Unsure, late or failed: private, as before. Instead of tainting the call, it keeps just
 * that turn private (markPrivate).
 */
class VoiceStatedFacts {
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
    if (turn.call.stated().some((stated) => hidden(stated, privateWords) || !statedFactIrrelevant(stated, turn.frame))) {
      return this._private(turn, DEPENDS_REASON);
    }
    return null;
  }

  _private(turn, reason) {
    turn.call.markPrivate(turn.text);
    return new Verdict(this.name, reason, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

module.exports = { PrivateChain, FollowUpWithoutContext, CallContextTaint, VoiceStatedFacts };
