"use strict";

// Stage 3 rules (save): answers right for this caller only (identifiers, private words, values, claims).

const { OUTCOME } = require("../../turns/values.js");
const { Verdict } = require("../../turns/values.js");
const { unfinished } = require("../../understanding/wordRules/followUp.js");
const { identifiers, leaks, repeatsIdentifier } = require("../../understanding/wordRules/identifiers.js");
const { repeatsPromptDetails } = require("../../understanding/wordRules/promptDetails.js");
const { escapeRegExp, wordsOf } = require("../../understanding/wordRules/text.js");
const { COUNTER } = require("../../runtime/stats.js");
const { ACTION_CLAIM, EMAIL, LONG_DIGITS } = require("../../understanding/answerPatterns.js");

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

// The ChatCallerIdentifier rule (stage 3, save; Chat).
/**
 * Voice's CallerIdentifier on Chat (v4): an answer repeating an ID-like value the user said anywhere in
 * this chat (an order number, an email, a long digit group), even in a turn that was shared, is never
 * shared, unless the shared question itself has it.
 */
class ChatCallerIdentifier {
  get name() {
    return "ChatCallerIdentifier";
  }

  get floor() {
    return false;
  }

  check(answer) {
    const asked = identifiers([answer.verdict.question || ""]);
    if (![...identifiers([answer.text])].some((value) => !asked.has(value) && answer.state.saidIdentifier(value))) return null;
    return new Verdict(this.name, "caller_identifier");
  }
}

// The IdentifyingAnswer rule (stage 3, save; Chat, "identifying").
/** An answer holding an email, a long digit run, or a detail the frame tagged as identifying is never shared. */
class IdentifyingAnswer {
  get name() {
    return "IdentifyingAnswer";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const t = answer.text;
    const tagged = Boolean(answer.frame) && answer.frame.identifyingTexts.some((x) => t.toLowerCase().includes(x.toLowerCase()));
    if (!(EMAIL.test(t) || LONG_DIGITS.test(t) || tagged)) return null;
    return new Verdict(this.name, "identifying");
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

// The ChatPromptDetails rule (stage 3, save; Chat, "prompt_detail").
/** An answer repeating a detail the system prompt gives about this user ("Hi Asha!") is right for this user only. */
class ChatPromptDetails {
  get name() {
    return "ChatPromptDetails";
  }

  get floor() {
    return true;
  }

  check(answer) {
    if (!answer.instructions || !repeatsPromptDetails(answer.text, answer.verdict.question || "", answer.instructions, answer.promptKey)) {
      return null;
    }
    return new Verdict(this.name, "prompt_detail");
  }
}

// The PrivateWord rule (stage 3, save; Chat, "private_word").
/**
 * A word that identified the user in a turn that was not shared ("Sarah", "55512") is never in a
 * shared answer, unless the shared question itself has it.
 */
class PrivateWord {
  get name() {
    return "PrivateWord";
  }

  get floor() {
    return true;
  }

  check(answer) {
    const asked = new Set(wordsOf(answer.verdict.question || ""));
    if (!wordsOf(answer.text).some((w) => !asked.has(w) && answer.state.isPrivate(w))) return null;
    return new Verdict(this.name, "private_word");
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
    if (!wordsOf(answer.answer).some((w) => !asked.has(w) && privateWords.has(w))) return null;
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

// The ActionClaim rule (stage 3, save; Chat, "action_claim").
/** An answer saying something was done for this user ("I have cancelled your order") is not shared. */
class ActionClaim {
  get name() {
    return "ActionClaim";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (!ACTION_CLAIM.test(answer.text)) return null;
    return new Verdict(this.name, "action_claim");
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

// The AttributeNotInKey rule (stage 3, save; Chat, "attribute_not_in_key").
/**
 * An answer that names one of this chat's attributes (a region, a tier) which did not enter the key
 * would reach users it does not fit. A value the question itself says ("the capital of France") is
 * part of what was asked.
 */
class AttributeNotInKey {
  get name() {
    return "AttributeNotInKey";
  }

  get floor() {
    return false;
  }

  check(answer) {
    const verdict = answer.verdict;
    for (const [name, attr] of Object.entries(answer.state.attributes)) {
      const pattern = attr.value ? new RegExp(`\\b${escapeRegExp(attr.value)}\\b`, "i") : null;
      if (!(name in verdict.attributes) && pattern && pattern.test(answer.text) && !pattern.test(verdict.question || "")) {
        return new Verdict(this.name, "attribute_not_in_key");
      }
    }
    return null;
  }
}

module.exports = { CallerIdentifier, ChatCallerIdentifier, IdentifyingAnswer, PromptCallerDetails, ChatPromptDetails, PrivateWord, VoicePrivateWord, DeclaredValue, PersonalTemplate, ActionClaim, VoiceActionClaim, AttributeNotInKey };
