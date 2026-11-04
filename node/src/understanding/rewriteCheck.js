"use strict";

const { leaks } = require("./wordRules/identifiers.js");
const { isPersonal } = require("./wordRules/personal.js");
const { numbersOf, properNouns, wordsOf } = require("./wordRules/text.js");

/**
 * The rewrite to key the turn on, or null for the caller's words. A rewrite keys a turn only when that
 * cannot make the call less private. The turn must be neither personal nor a follow-up, by its reading
 * or the word rules (a follow-up keeps its chain as the key, so the key says what the model was shown);
 * the rewrite must not read as personal, carry a declared value, or add a number or a name the caller did
 * not say. Once the caller has told the call something, no rewrite is used: the classifier read those
 * facts, and a rewrite could carry one into a shared key. Anything else keeps the caller's words.
 */
function acceptedRewrite(text, reading, rewritten, call) {
  if (typeof rewritten !== "string" || !rewritten.trim()) return null;
  if (call.stated().length || call.facts().length) return null;
  if (reading.isPersonal || call.isPersonal(text)) return null;
  if (reading.isContextDependent || call.isContextDependent(text)) return null;
  if (isPersonal(rewritten) || leaks(rewritten, call.values) || addsDetails(text, rewritten)) return null;
  return rewritten.trim();
}

function addsDetails(text, rewritten) {
  const saidNumbers = new Set(numbersOf(text));
  if (numbersOf(rewritten).some((number) => !saidNumbers.has(number))) return true;
  const saidWords = new Set(wordsOf(text).map(stemOf));
  return [...properNouns(rewritten)].some((name) => !saidWords.has(stemOf(name)));
}

/** A word without case or a plural "s", so "Sunday" in a rewrite matches "sundays" said. */
function stemOf(word) {
  return word.toLowerCase().replace(/s+$/, "");
}

module.exports = { acceptedRewrite };
