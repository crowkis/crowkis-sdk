"use strict";

// The word rules for high-risk stated facts: an allergy, a medication, a pregnancy, an age. A shared
// answer is never given without such a fact once the caller has stated it, whatever a model says.

const { AGE_WORDS, TREATMENTS } = require("./callContext.js");
const { wordsOf } = require("./text.js");

// The fact types that always change an answer (the floor under StatedFacts' relevance).
const HIGH_RISK_FACT_TYPES = new Set(["allergy", "medication", "pregnancy", "age"]);

// "I'm allergic to peanuts", "intolerant to lactose".
const ALLERGY_WORDS = new Set([
  "allergic", "allergy", "allergies", "intolerant", "intolerance", "anaphylaxis", "anaphylactic", "celiac", "coeliac",
]);
// "I'm on insulin", "she takes blood thinners".
const MEDICATION_WORDS = new Set([...TREATMENTS, "prescription", "prescribed", "dose", "dosage", "tablets", "meds"]);
// "I'm pregnant", "breastfeeding".
const PREGNANCY_WORDS = new Set(["pregnant", "pregnancy", "expecting", "trimester", "breastfeeding", "nursing", "postpartum"]);
// "my 3 year old", "a toddler", "she is 80": an age, or a word that is one.
const AGE_STAGE_WORDS = new Set(["aged", "toddler", "infant", "baby", "newborn", "elderly", "senior", "teenager", "teen"]);

/** The text states an allergy, a medication, a pregnancy or an age. */
function highRisk(text) {
  const words = wordsOf(text);
  if (words.some((w) => ALLERGY_WORDS.has(w) || MEDICATION_WORDS.has(w) || PREGNANCY_WORDS.has(w) || AGE_STAGE_WORDS.has(w))) {
    return true;
  }
  return words.some((w) => /^\d+$/.test(w)) && words.some((w) => AGE_WORDS.has(w));
}

module.exports = { HIGH_RISK_FACT_TYPES, highRisk };
