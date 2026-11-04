"use strict";

// Stage 1 rules (question): about this caller (own records, identifying details, someone else, a name).

const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { CALENDAR, COMMON_ACRONYMS, FUNCTION, looksIdentifying } = require("../../understanding/frameWords.js");
const { NOT_GENERAL_TYPES } = require("../../understanding/turnFrame.js");
const { wordsOf } = require("../../understanding/wordRules/index.js");
const { wordDigest } = require("../../state/callState.js");

const OWN_RECORDS_REASON =
  "the caller asked about their own records and this session has no values " +
  "to fill a shared answer shape with, so nothing can be answered from " +
  "cache without one caller's answer reaching the next";

/**
 * A question about the caller's own records ("where is my order 48213"), or another turn the
 * word rules never share (urgent, identifying, unreadable), is never answered from the shared
 * cache unless this call declared values to fill a shared answer shape with.
 */
class OwnRecords {
  get name() {
    return "OwnRecords";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!turn.isPersonal || turn.call.hasValues) return null;
    return new Verdict(this.name, OWN_RECORDS_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

// The IdentifyingDetails rule (stage 1, question; Chat, V5).
/** An identifying entity, an email, a phone number or an ID-like digit run never enters a key. */
class IdentifyingDetails {
  get name() {
    return "IdentifyingDetails";
  }

  get floor() {
    return true;
  }

  check(turn) {
    const question = turn.question;
    const low = question.toLowerCase();
    if (!(turn.frame.identifyingTexts.some((t) => low.includes(t.toLowerCase())) || looksIdentifying(question))) return null;
    return new Verdict(this.name, "V5_identifying");
  }
}

// The AboutSomeone rule (stage 1, question; Chat, V4).
/** An owned record, an own purchase or another person in the frame contradicts "general". */
class AboutSomeone {
  get name() {
    return "AboutSomeone";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!turn.frame.entities.some((e) => NOT_GENERAL_TYPES.has(e.type))) return null;
    return new Verdict(this.name, "V4_about_someone");
  }
}

// The QuestionNamesCaller rule (stage 1, question; Chat, "V5_private_word", checked once the rule checker would share).
/** The shared question says what named the caller earlier ("for sarah"). */
class QuestionNamesCaller {
  get name() {
    return "QuestionNamesCaller";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!wordsOf(turn.question || "").some((w) => turn.state.isName(w))) return null;
    return new Verdict(this.name, "V5_private_word");
  }
}

// The UntaggedName rule (stage 1, question; Chat, "V5_untagged_name", checked once the rule checker would share).
/**
 * A word in the shared question with a capital ("Priya", "PRIYA", "McKenzie"), or in a script without
 * capitals, that the understanding model did not tag as a place, thing or topic, that is no month or
 * day, and that no earlier shared turn of this chat said. Fixed code cannot tell "Priya" from
 * "France" or "SSO"; the model's tag can (it is asked to tag every one).
 */
class UntaggedName {
  get name() {
    return "UntaggedName";
  }

  get floor() {
    return true;
  }

  check(turn) {
    const state = turn.state;
    const allowed = new Set(turn.frame.entities.filter((e) => !e.identifying && !NOT_GENERAL_TYPES.has(e.type)).flatMap((e) => wordsOf(e.text)));
    for (const w of [...CALENDAR, ...wordsOf(state.activeQuestion || ""), ...wordsOf(state.lastReply)]) allowed.add(w);
    const flagged = new Set();
    (String(turn.question || "").match(/\p{L}+/gu) || []).forEach((word, i) => {
      const low = word.toLowerCase();
      if (word === "I" || (i === 0 && FUNCTION.has(low))) return; // "What ...", "How ..."
      if (word === word.toUpperCase() && COMMON_ACRONYMS.has(low)) return; // "UPI", "SIM": a thing, never "Ram" or "Sim"
      if (/[\p{Lu}\p{Lt}\p{Lo}]/u.test(word)) flagged.add(low);
    });
    if (![...flagged].some((w) => !allowed.has(w) && !state.details.includes(wordDigest(w)))) return null;
    return new Verdict(this.name, "V5_untagged_name");
  }
}

module.exports = { OwnRecords, IdentifyingDetails, AboutSomeone, QuestionNamesCaller, UntaggedName };
