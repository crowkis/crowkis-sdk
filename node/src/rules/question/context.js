"use strict";

// Stage 1 rules (question): what the call said before (a private chain, a follow-up, a reference, stated facts).

const { Verdict } = require("../../turns/verdict.js");
const { leansOn, privateChain, setsContext, wordsOf } = require("../../understanding/wordRules/index.js");
const { COUNTER } = require("../../runtime/stats.js");
const {
  CLAUSE_START,
  CONTRACTION,
  FUNCTION,
  GENERIC_FACT,
  NUMWORDS,
  QUESTION_WORDS,
  REFERRING,
  stem,
  toks,
} = require("../../understanding/frameWords.js");
const { FactRelevanceCheck } = require("../../understanding/factRelevance.js");
const { unnamed } = require("../../understanding/chatDetails.js");
const { wordDigest } = require("../../state/callState.js");
const { DETAIL_TYPES } = require("../../understanding/turnFrame.js");

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

// The UnresolvedReference rule (stage 1, question; Chat, V10).
/**
 * The model says the turn leans on the chat ("how far is it from London?") but the turn or its
 * question says "it" and the question names nothing new from the chat (a neutral "population" names
 * nothing; "Who is their president?" -> "Who is the president?" dropped it): the reference was not
 * resolved. A rewrite that resolved it ("Is it safe to eat pad thai in Thailand?") keeps a filler
 * "it" and is fine.
 */
class UnresolvedReference {
  get name() {
    return "UnresolvedReference";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const saidList = toks(turn.text);
    const said = new Set(saidList);
    const qwords = toks(turn.question);
    const named = qwords.some((w) => !said.has(w) && !FUNCTION.has(w) && !QUESTION_WORDS.has(w) && !CONTRACTION.has(w));
    // shortcut: Chat checks only the last shared question; after a personal turn this misses (as before).
    const leans = leansOn(turn.question, turn.state.activeQuestion || "");
    if (!(leans || (turn.frame.usesState && [...qwords, ...saidList].some((w) => REFERRING.has(w)) && !named))) return null;
    return new Verdict(this.name, "V10_unresolved");
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

// The StatedFacts rule (stage 1, question; Chat, V7).
/**
 * A fact the caller stated in this chat (an allergy, an age, a trip) that the question does not
 * carry. Fixed code, so the allergy case never rests on the model having tagged the allergy: the
 * question must keep at least one content word of each such turn. A turn with no readable word
 * (another script) cannot be checked, so it keeps the question private.
 *
 * v4: a stated turn the frame confidently tags as not changing this answer may be left out
 * (FactRelevanceCheck); an allergy, a medication, a pregnancy or an age never may.
 */
class StatedFacts {
  constructor({ relevance = new FactRelevanceCheck() } = {}) {
    this._relevance = relevance;
  }

  get name() {
    return "StatedFacts";
  }

  get floor() {
    return false;
  }

  check(turn) {
    for (const dropped of StatedFacts._droppedStatements(turn.state, turn.question)) {
      if (!this._relevance.irrelevant(dropped, turn.frame)) return new Verdict(this.name, "V7_lost:" + dropped);
    }
    return null;
  }

  static *_droppedStatements(state, question) {
    const qstems = new Set(toks(question).map(stem));
    for (const turn of state.stated) {
      let words = toks(turn).filter((w) => !FUNCTION.has(w) && (w.length > 2 || /^\d+$/.test(w)));
      // "allergies" alone does not carry "allergic to penicillin": the specific word must be there.
      const specific = words.filter((w) => !GENERIC_FACT.has(stem(w)));
      if (specific.length) words = specific;
      if (!words.length || !words.some((w) => qstems.has(stem(w))) || StatedFacts._dropsAListedItem(turn, qstems)) {
        yield turn;
      }
    }
  }

  /** Every item of a list is carried: "penicillin and peanuts" is not "peanuts". */
  static _dropsAListedItem(turn, qstems) {
    const all = toks(turn);
    for (let i = 0; i < all.length; i++) {
      // "and I live alone" starts a new clause; it is not a list.
      if ((all[i] !== "and" && all[i] !== "or") || (i + 1 < all.length && CLAUSE_START.has(all[i + 1]))) continue;
      for (const side of [all.slice(0, i).reverse(), all.slice(i + 1)]) {
        const item = side.find((x) => !FUNCTION.has(x));
        if (item && (item.length > 2 || /^\d+$/.test(item)) && !GENERIC_FACT.has(stem(item)) && !qstems.has(stem(item))) return true;
      }
    }
    return false;
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

// The ToldDetailDropped rule (stage 1, question; Chat, "V7_lost_detail", checked once the rule checker would share).
/** A place, month or number the caller told ("Goa in December") is missing from the question. */
class ToldDetailDropped {
  get name() {
    return "ToldDetailDropped";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const words = wordsOf(turn.question || "");
    const asked = new Set([...words.map(wordDigest), ...words.map((w) => wordDigest(NUMWORDS[w] || w))]); // "three" is "3"
    if (!turn.state.details.some((d) => !asked.has(d))) return null;
    return new Verdict(this.name, "V7_lost_detail");
  }
}

// The LostDetail rule (stage 1, question; Chat, V7).
/** An answer-relevant detail of the turn (a product, a time, a place) missing from the key. */
class LostDetail {
  get name() {
    return "LostDetail";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const lost = LostDetail._lostDetail(turn.frame, turn.question);
    if (!lost) return null;
    return new Verdict(this.name, "V7_lost:" + lost);
  }

  static _lostDetail(frame, question) {
    const qstems = new Set(toks(question).map(stem));
    const attrText = Object.values(frame.attributes).map((a) => `${a.value} ${a.normalised}`).join(" ").toLowerCase();
    for (const e of frame.entities) {
      if (e.answerRelevant && !e.identifying && DETAIL_TYPES.has(e.type)) {
        const words = toks(e.text).filter((w) => !FUNCTION.has(w));
        if (words.length && !words.some((w) => qstems.has(stem(w))) && !words.some((w) => attrText.includes(w))) return e.text;
      }
    }
    return null;
  }
}

module.exports = { PrivateChain, FollowUpWithoutContext, UnresolvedReference, CallContextTaint, StatedFacts, VoiceStatedFacts, ToldDetailDropped, LostDetail };
