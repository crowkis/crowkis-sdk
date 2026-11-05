"use strict";
const { HIGH_RISK_FACT_TYPES, highRisk } = require("../wordRules/callContext.js");
const { FUNCTION, stem, toks } = require("../wordRules/privateWords.js");
const { leaks, isPersonal } = require("../wordRules/personal.js");
const { numbersOf, properNouns, wordsOf } = require("../wordRules/text.js");
const { CONFIDENCE_FLOOR } = require("./frame.js");

// Where a stated turn holds a second fact: "going to Goa and my husband has a heart condition", "with my son who uses a wheelchair".
const CLAUSE_BREAK = /[,;.!?]|\b(?:and|but|also|plus|aur|y|with|who|whose|which|because|since|so|while|after)\b/i;

/**
 * A stated turn ("my car was hit") may be left out of a shared question only when the model is sure
 * of the turn (not abstaining, at or above the confidence floor) and tags the fact as not changing
 * this answer, and only when neither the stated words nor the model's type say allergy, medication,
 * pregnancy or age (the floor). Late, failed, unsure or silent: the fact counts. Each clause of a stated
 * turn is a fact of its own and needs its own "does not change" entry.
 */
function statedFactIrrelevant(stated, frame) {
  if (!frame || frame.abstain || frame.confidence < CONFIDENCE_FLOOR || highRisk(stated)) return false;
  return clauses(stated).every((clause) => clauseIrrelevant(clause, frame));
}

function clauseIrrelevant(clause, frame) {
  const stems = contentStems(clause);
  const about = (frame.factRelevance || []).filter((f) => [...contentStems(f.fact)].some((s) => stems.has(s)));
  return about.length > 0 && !about.some((f) => f.changesAnswer || HIGH_RISK_FACT_TYPES.has(f.type));
}

/** The parts of a stated turn that say something (at least one content word). */
function clauses(stated) {
  const parts = stated.split(new RegExp(CLAUSE_BREAK.source, "gi")).filter((part) => part && contentStems(part).size);
  return parts.length ? parts : [stated];
}

function contentStems(text) {
  return new Set(toks(text).filter((w) => !FUNCTION.has(w) && w.length > 2).map(stem));
}

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

module.exports = { statedFactIrrelevant, contentStems, acceptedRewrite };
