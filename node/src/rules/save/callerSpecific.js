"use strict";

// Stage 3 rules (save): answers right for this caller only (identifiers, private words, values, claims).

const { OUTCOME } = require("../../turns/values.js");
const { Verdict } = require("../../turns/values.js");
const { unfinished } = require("../../understanding/wordRules/followUp.js");
const { bare, leaks, repeatsIdentifier } = require("../../understanding/wordRules/personal.js");
const { repeatsPromptDetails } = require("../../understanding/wordRules/answers.js");
const { wordsOf } = require("../../understanding/wordRules/text.js");
const { COUNTER } = require("../../runtime/stats.js");
const { ACTION_CLAIM } = require("../../understanding/wordRules/privateWords.js");

/**
 * An answer repeating a number or ID this caller said is never shared. Its model read only the
 * question, so this can only come from an app that sent it the whole call.
 */
class CallerIdentifier {
  get name() {
    return "CallerIdentifier";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!repeatsIdentifier(answer.answer, answer.call.saidIdentifiers())) return null;
    return new Verdict(this.name, "kept to this call: the answer repeats a number or ID this caller said",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

/**
 * The model read a system prompt that names this caller, and its answer repeats that: right for
 * this caller only, never a shared answer or shape.
 */
class PromptCallerDetails {
  get name() {
    return "PromptCallerDetails";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.instructions || !repeatsPromptDetails(answer.answer, answer.text, answer.instructions, answer.call.agentKey())) {
      return null;
    }
    return new Verdict(this.name, "kept to this call: the answer repeats a detail about the caller from the system prompt",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

// The VoicePrivateWord rule (stage 3, save; voice with an understander).
/**
 * Chat's PrivateWord on voice (v4): a word that identified the caller in a turn kept private ("Sarah",
 * "55512") is never in a shared answer, unless the shared question itself has it.
 */
class VoicePrivateWord {
  get name() {
    return "VoicePrivateWord";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const asked = new Set(wordsOf(answer.key || ""));
    const privateWords = answer.call.privateWords();
    if (!wordsOf(answer.answer).some((w) => !asked.has(w) && (privateWords.has(w) || privateWords.has(bare(w))))) return null;
    return new Verdict(this.name, "kept to this call: the answer holds a word that identified this caller",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

/** An answer holding a value declared for this call is never shared. */
class DeclaredValue {
  get name() {
    return "DeclaredValue";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!leaks(answer.answer, answer.call.values)) return null;
    return new Verdict(this.name, "kept to this call: the answer contains a value declared for this call",
      [COUNTER.NOT_SHAREABLE], OUTCOME.PRIVATE);
  }
}

/**
 * An answer about the caller's own records is shared only as a shape with this call's declared
 * values taken out; this rule says when it cannot be (the call was told something, the answer
 * does not answer, the turn was cut off, or no shape could be made).
 */
class PersonalTemplate {
  get name() {
    return "PersonalTemplate";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.isPersonal) return null;
    if (answer.call.tainted || answer.isNonAnswer || unfinished(answer.text)) return this.refusal();
    return null;
  }

  /** The verdict when no shared shape is made from a personal answer. */
  refusal() {
    return new Verdict(this.name, "about this caller, with no declared value to make a shared answer shape from", [], OUTCOME.PRIVATE);
  }
}

// The VoiceActionClaim rule (stage 3, save; voice with an understander).
/**
 * Chat's ActionClaim on voice (v4): an answer saying something was done for this caller ("I have
 * cancelled your order") is not shared.
 */
class VoiceActionClaim {
  get name() {
    return "VoiceActionClaim";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!ACTION_CLAIM.test(answer.answer || "")) return null;
    return new Verdict(this.name, "kept to this call: the answer says something was done for this caller",
      [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

module.exports = { CallerIdentifier, PromptCallerDetails, VoicePrivateWord, DeclaredValue, PersonalTemplate, VoiceActionClaim };
