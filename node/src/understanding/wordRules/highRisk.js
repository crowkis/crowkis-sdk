"use strict";

// The word rules for high-risk stated facts: an allergy, a medication, a pregnancy, an age, a serious
// condition. A shared answer is never given without such a fact once the caller has stated it, whatever a
// model says.

const { AGE_WORDS, TREATMENTS } = require("./callContext.js");
const { wordsOf } = require("./text.js");

// The fact types that always change an answer (the floor under StatedFacts' relevance).
const HIGH_RISK_FACT_TYPES = new Set(["allergy", "medication", "pregnancy", "age"]);

// "I'm allergic to peanuts", "intolerant to lactose".
const ALLERGY_WORDS = new Set([
  "allergic", "allergy", "allergies", "intolerant", "intolerance", "anaphylaxis", "anaphylactic", "celiac", "coeliac",
]);
// "I'm on insulin", "she takes warfarin": a treatment, a dose, or a common drug by name.
const MEDICATION_WORDS = new Set([...TREATMENTS,
  "prescription", "prescribed", "dose", "dosage", "tablets", "meds", "warfarin", "metformin", "aspirin", "ibuprofen",
  "paracetamol", "acetaminophen", "statin", "statins", "lisinopril", "amoxicillin", "penicillin", "prednisone",
  "levothyroxine", "antidepressants", "ssri", "opioids", "morphine", "inhaler", "chemo",
]);
// "I'm diabetic", "he had a stroke": a condition that changes what is safe for the caller.
const CONDITION_WORDS = new Set([
  "diabetic", "diabetes", "kidney", "kidneys", "renal", "epilepsy", "epileptic", "seizure", "seizures", "asthma",
  "asthmatic", "stroke", "heart", "cardiac", "cancer", "hypertension", "cirrhosis", "liver", "hiv", "pacemaker",
  "copd", "dementia", "alzheimer", "alzheimers", "arthritis", "thyroid", "anemia", "anaemia", "hemophilia",
]);
// "I'm pregnant", "breastfeeding", "estoy embarazada", "8 months along".
const PREGNANCY_WORDS = new Set([
  "pregnant", "pregnancy", "expecting", "trimester", "breastfeeding", "nursing", "postpartum", "embarazada",
  "embarazo", "garbhvati", "pregnent",
]);
const PREGNANCY_PHRASES = [["months", "along"], ["weeks", "along"], ["weeks", "pregnant"], ["months", "pregnant"]];
// "a toddler", "she is elderly": an age by its stage.
const AGE_STAGE_WORDS = new Set(["aged", "toddler", "infant", "baby", "newborn", "elderly", "senior", "teenager", "teen", "yo", "yrs"]);
// Who an age may be said of ("my son is 3", "she is 80"): a person word next to a number makes it an age.
const PERSON_WORDS = new Set([
  "i", "im", "he", "she", "hes", "shes", "son", "daughter", "kid", "kids", "child", "children", "boy", "girl",
  "mother", "father", "mom", "mum", "dad", "grandmother", "grandfather", "grandma", "grandpa", "wife", "husband",
  "brother", "sister", "hijo", "hija", "beta", "beti", "bacha", "bachcha", "bachche",
]);
// Numbers said in words ("my daughter is three").
const NUMBER_WORDS = new Set(("one two three four five six seven eight nine ten eleven twelve thirteen fourteen " +
  "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred").split(" "));

const isNumber = (w) => /^\d+$/.test(w) || NUMBER_WORDS.has(w) || /^\d+yo$/.test(w);

/** The text states an allergy, a medication, a serious condition, a pregnancy or an age. */
function highRisk(text) {
  const words = wordsOf(text);
  const named = [ALLERGY_WORDS, MEDICATION_WORDS, CONDITION_WORDS, PREGNANCY_WORDS, AGE_STAGE_WORDS];
  if (words.some((w) => named.some((group) => group.has(w)))) return true;
  if (PREGNANCY_PHRASES.some(([a, b]) => words.some((w, i) => w === a && words[i + 1] === b))) return true;
  return words.some(isNumber) && words.some((w) => AGE_WORDS.has(w) || PERSON_WORDS.has(w));
}

module.exports = { HIGH_RISK_FACT_TYPES, highRisk };
