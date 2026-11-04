"use strict";
const { describesCaller, diagnosis, discloses, sensitiveSelf, unreadable } = require("./personal.js");
const {
  AMOUNT_WORDS,
  CALLER_KINDS,
  DISCOURSE,
  MATTERS,
  NUMBER_WORDS,
  OTHER_POSSESSIVES,
  POSSESSIVES,
  QUESTION_LEADS,
  WH_WORDS,
  clauseStarts,
  contains,
  firstWords,
  hasDigit,
  hasPhrase,
  properNouns,
  wordsOf,
  ACTION_LEADS_BY_FIRST,
  SOMEONE,
  STEERING,
} = require("./text.js");
const { urgent } = require("./urgent.js");

// What the caller told the call: conditions, plans, instructions, steps of their own task.


// What a caller tells the call can change the right answer to a later question
// ("I'm allergic to peanuts", then "is pad thai safe?"). The later question alone
// does not say so, so after such a turn nothing in the call is looked up or shared.
const BIRTH_WORDS = new Set([
  "born", "birth", "dob", "birthday", "nasci", "naci", "nací", "nacido", "nacida", "nascido",
  "nascida", "né", "née", "paida", "janam",
]);
// What the caller is, has or plans: "I'm vegetarian", "I am 65", "we're travelling".
const SELF_STATES = [["i", "am"], ["i", "m"], ["we", "are"], ["we", "re"], ["soy"], ["estoy"], ["main"], ["je", "suis"]];
const HAVING = [["i", "have"], ["we", "have"], ["i", "ve", "got"], ["we", "ve", "got"], ["tengo"], ["mujhe"]];
const MY = new Set([...POSSESSIVES, ...OTHER_POSSESSIVES, "mera", "meri", "mere"]);
// Said after "I'm" or "I have", each of these is something about the caller that can change an answer.
const SELF_ATTRIBUTES = new Set([
  "vegetarian", "vegan", "pescatarian", "diabetic", "allergic", "pregnant", "lactose", "gluten",
  "celiac", "coeliac", "intolerant", "retired", "disabled", "deaf", "blind", "married", "single",
  "divorced", "widowed", "unemployed", "employed", "pensioner", "senior", "student", "beginner",
  "expert", "elderly", "nursing", "breastfeeding", "shakahari", "vegetariano", "vegetariana",
  "vegano", "vegana", "diabético", "diabética", "alérgico", "alérgica", "embarazada", "estudiante",
  "jubilado", "jubilada", "né", "née", "nacido", "nacida", "self", "migraine", "migraines", "arthritis",
  "hypertension", "cholesterol", "thyroid", "epilepsy", "fever", "flu", "cough", "headache", "injury",
  "surgery", "eczema", "psoriasis", "ulcer", "bp", "sugar", "keto", "halal", "kosher", "pacemaker",
  "implant", "stent",
]);
// "I'm travelling to Goa": a plan, only with where to ("I'm planning to cancel" is not one).
const PLAN_VERBS = new Set(["visiting", "planning", "travelling", "traveling", "moving", "relocating", "flying", "going", "hosting"]);
// "I'm 5 minutes away", "we're 10 minutes late": a number that is not an age.
const NOT_AGE_UNITS = new Set([
  "minute", "minutes", "mins", "min", "hour", "hours", "hrs", "second", "seconds", "secs", "km", "kms",
  "mile", "miles", "meters", "metres", "blocks", "day", "days", "week", "weeks", "orders", "items",
  "steps", "times", "percent", "pm", "am",
]);
const AGE_WORDS = new Set(["year", "years", "yr", "yrs", "old", "saal", "años", "ans", "anos"]);
// Doing something to the caller's own booking, order or account ("change my flight",
// "cancel my order"): the turns after it are steps in that task. Looking at it ("check my
// order", "track my parcel") is not.
const CHANGE_VERBS = new Set([
  "cancel", "book", "reschedule", "change", "update", "delete", "remove", "transfer", "refund", "replace",
  "exchange", "return", "upgrade", "downgrade", "activate", "deactivate", "close", "renew", "reserve",
  "move", "modify", "rebook", "postpone", "extend", "pause", "resume", "block", "unblock",
]);
// "I'm on blood thinners": a treatment the caller is on.
const TREATMENTS = new Set([
  "blood", "medication", "medicine", "medicines", "insulin", "dialysis", "chemo", "chemotherapy",
  "antibiotics", "steroids", "thinners", "pills", "treatment", "oxygen",
]);
const ARTICLE_FILLERS = new Set(["bit", "little", "lot", "few", "couple"]);
const GENERIC_ROLES = new Set(["customer", "customers", "user", "users", "buyer", "client", "guest", "visitor", "shopper"]);
// "I have a question" asks; "I have a 3 year old daughter" tells.
const HAVE_NOT = new Set([
  "question", "questions", "query", "doubt", "quick", "general", "problem", "issue", "complaint",
  "request", "minute", "moment", "second", "look", "few", "couple", "idea", "feeling", "bit", "more",
  "thing", "things", "pregunta", "duda", "problema", "momento", "queja",
]);
const PLANS = new Set(["trip", "vacation", "holiday", "wedding"]);
// Part of the caller's life: told about, it can change an answer.
const LIFE_WORDS = new Set([
  "income", "salary", "age", "family", "wife", "husband", "son", "daughter", "kids", "children",
  "child", "baby", "parents", "mother", "father", "mom", "mum", "dad", "farm", "business", "company",
  "shop", "health", "condition", "disability", "pension", "loan", "debt", "religion", "diet", "budget",
  "partner", "grandmother", "grandfather", "sister", "brother", "kid", "dog", "cat", "pet", "beta",
  "beti", "maa", "papa", "umar", "bachche", "bacha", "hijo", "hija", "hijos", "madre", "padre",
  "esposa", "esposo", "edad", "newborn", "twins", "dogs", "cats", "pets", "diet", ...PLANS,
]);
// "my loan is not showing": a problem with the thing, not a fact about the caller.
const NOT_TOLD = new Set([
  "not", "no", "still", "showing", "missing", "pending", "stuck", "blocked", "late", "delayed", "down",
  "broken", "wrong", "gone",
]);
// "my son is 12", "my budget is", "mera beta 12 saal ka hai": a life word told, not asked about.
const TELLING_VERBS = new Set([
  "is", "s", "has", "was", "are", "have", "had", "needs", "takes", "lives", "works", "eats", "hai",
  "es", "tiene",
]);
// How the caller wants answers from now on ("reply only in Hindi", "keep it short"), or what
// they live by ("I don't eat meat"). Counted only where a clause starts, so "can I keep it"
// and "is it available only in red" are not instructions.
const INSTRUCTIONS = [
  ...STEERING,
  ["reply", "in"], ["reply", "only"], ["respond", "in"], ["respond", "only"], ["answer", "in"],
  ["answer", "only"], ["speak", "in"], ["talk", "in"], ["talk", "to", "me", "in"], ["write", "in"],
  ["keep", "it"], ["keep", "answers"], ["keep", "your"], ["explain", "like"],
  ["speak", "slowly"], ["speak", "slower"], ["use", "metric"], ["responde", "en"], ["habla", "en"],
  ["i", "don", "t", "eat"], ["i", "do", "not", "eat"], ["we", "don", "t", "eat"], ["i", "take"],
  ["i", "earn"], ["we", "earn"], ["i", "only", "speak"], ["i", "don", "t", "speak"], ["i", "was", "born"],
  ["talk", "to", "me", "like"], ["vivo", "en"], ["i", "can", "t", "have"], ["i", "cannot", "have"],
  ["i", "keep", "halal"], ["i", "keep", "kosher"], ["i", "live", "alone"], ["i", "live", "with"],
];
// Said anywhere: "mujhe Hindi mein jawab do".
const INSTRUCTIONS_ANYWHERE_BY_FIRST = firstWords([["mein", "jawab"], ["mein", "baat"], ["mein", "bolo"], ["en", "español"], ["en", "inglés"]]);
// "forget it", "ignore that", "I take it", "speak in a minute", "just keep it": after these
// phrases, a word like these (or nothing) means it is not an instruction.
const NOT_AN_OBJECT = new Set(["it", "that", "this", "about", "the", "a", "an", "care", "you", "your", "my", "to"]);
const NEEDS_AN_OBJECT = new Set([
  "forget", "ignore", "assume", "pretend", "i take", "keep it", "reply in", "respond in", "answer in",
  "speak in", "talk in", "write in", "talk to me in",
]);
function instructs(text, words) {
  if (hasPhrase(words, INSTRUCTIONS_ANYWHERE_BY_FIRST)) return true;
  for (const start of clauseStarts(text)) {
    for (const phrase of INSTRUCTIONS) {
      const end = phrase.length;
      if (!phrase.every((w, k) => start[k] === w)) continue;
      if (!NEEDS_AN_OBJECT.has(phrase.join(" ")) || (end < start.length && !NOT_AN_OBJECT.has(start[end]))) return true;
    }
  }
  return false;
}

function leadsAt(words, index, lead) {
  return lead.every((w, k) => words[index + k] === w);
}

function statesSelf(text, words) {
  const places = properNouns(text);
  for (let index = 0; index < words.length; index += 1) {
    for (const lead of SELF_STATES) {
      const end = index + lead.length;
      if (!leadsAt(words, index, lead) || end >= words.length) continue;
      const x = words[end];
      const after = words.slice(end + 1, end + 3);
      if (x === "a" || x === "an") {
        if (after.length && !ARTICLE_FILLERS.has(after[0]) && !after.some((w) => GENERIC_ROLES.has(w))) return true;
      } else if (hasDigit(x) || AMOUNT_WORDS.has(x)) {
        if (!(after.length && NOT_AGE_UNITS.has(after[0]))) return true; // "I'm 65", not "I'm 5 minutes away"
      } else if (SELF_ATTRIBUTES.has(x) || CALLER_KINDS.has(x)) {
        return true;
      } else if (PLAN_VERBS.has(x)) {
        // "I'm travelling to Goa", not "I'm planning to cancel"
        if (words.slice(end + 1, end + 5).some((w) => PLANS.has(w) || places.has(w) || LIFE_WORDS.has(w))) return true;
      } else if ((x === "in" || x === "from" || x === "de") && after.length && places.has(after[0])) {
        return true; // "I'm in Pune"
      } else if (x === "on" && words.slice(end + 1, end + 4).some((w) => TREATMENTS.has(w) || SELF_ATTRIBUTES.has(w) || w === "diet")) {
        return true; // "I'm on blood thinners", "I'm on a keto diet"
      }
    }
    for (const lead of HAVING) {
      const end = index + lead.length;
      if (!leadsAt(words, index, lead) || end >= words.length) continue;
      const told = words.slice(end, end + 6);
      if (told.some((w) => HAVE_NOT.has(w))) continue;
      // "I have two kids", "I have a 3 year old daughter"
      if (told.some((w) => LIFE_WORDS.has(w) || MATTERS.has(w) || SELF_ATTRIBUTES.has(w))) return true;
      // "tengo 65 años"; "I have 2 orders pending" is not
      if (told.some((w) => hasDigit(w) || AMOUNT_WORDS.has(w)) && told.some((w) => AGE_WORDS.has(w))) return true;
    }
    if (MY.has(words[index]) && index + 2 < words.length && LIFE_WORDS.has(words[index + 1])) {
      let told = words[index + 2];
      const then = index + 3 < words.length ? words[index + 3] : "";
      // "my wife's card" is not "my wife is ..."
      if (told === "s") told = hasDigit(then) || NUMBER_WORDS.has(then) ? then : "";
      if ((TELLING_VERBS.has(told) && !NOT_TOLD.has(then)) || hasDigit(told) || NUMBER_WORDS.has(told)) return true;
    }
  }
  return false;
}

// "I want to change my flight", "cancel my order": a step in the caller's own task,
// with "my" right after what is to be done. "Let me check my email" is the caller's.
function actsOnOwn(words) {
  const lead = words.find((w) => !DISCOURSE.has(w));
  const asksFor = hasPhrase(words, ACTION_LEADS_BY_FIRST) && !contains(words, ["let", "me"]);
  if (!(asksFor || CHANGE_VERBS.has(lead))) return false;
  return words.some((w, i) => CHANGE_VERBS.has(w) && words.slice(i + 1, i + 3).some((o) => POSSESSIVES.has(o)));
}

// The live rule's "who the caller is", less "I'm on ...": "I'm on hold" and "I'm on the
// website" say where the call is, not who is calling ("I'm on the premium plan" still
// counts through the plan's name).
function describesSelf(words) {
  const on = contains(words, ["i", "m", "on"]) || contains(words, ["i", "am", "on"]);
  return describesCaller(words) && (!on || words.some((w) => CALLER_KINDS.has(w)));
}

// Whether this turn tells the call something later answers may depend on, said on its
// own or inside a question: a health, legal or money matter, an emergency, a step in the
// caller's own task, what the caller is, has or plans ("I'm vegetarian", "I have a 3 year
// old daughter", "I'm planning a trip to Goa"), a date of birth, or how to answer from now
// on ("reply only in Hindi"). Each is a match on what was said, never a default: small
// talk, "I have a question", "I'm frustrated", "I have 2 orders" and a name or number change no answer, and a
// call that starts with them keeps its shared answers.

function setsContext(text) {
  const words = wordsOf(text);
  return tellsFacts(text) || (words.length > 0 && instructs(text, words));
}

// `setsContext` without instructions: what the caller is, has, plans or is doing about their
// own task. A later shared question must carry these; a "reply in Hindi" is carried by the
// reply language instead.
// `tellsFacts` for a chat's memory and its emergency check: a question that only asks about a
// matter ("what are the symptoms of a heart attack?", "how do I treat a burn?") tells nothing
// about the caller. What the caller is or has, said inside a question, still counts.
function tellsAboutCaller(text) {
  const words = wordsOf(text);
  if (words.length && (WH_WORDS.has(words[0]) || QUESTION_LEADS.has(words[0])) &&
      !words.some((w) => POSSESSIVES.has(w) || SOMEONE.has(w))) {
    return describesSelf(words) || statesSelf(text, words) || words.some((w) => BIRTH_WORDS.has(w));
  }
  return tellsFacts(text);
}

function tellsFacts(text) {
  const words = wordsOf(text);
  return words.length > 0 && (
    unreadable(text) || discloses(words) || sensitiveSelf(words) || urgent(words) ||
    (diagnosis(words) && !words.some((w) => HAVE_NOT.has(w)) &&
      !["have", "tengo"].some((have) => ["a", "an", "un", "una", "el", "la"].some((article) => contains(words, [have, article])))) ||
    actsOnOwn(words) || describesSelf(words) || statesSelf(text, words) ||
    words.some((w) => BIRTH_WORDS.has(w))
  );
}

// The word rules for high-risk stated facts: an allergy, a medication, a pregnancy, an age, a serious
// condition. A shared answer is never given without such a fact once the caller has stated it, whatever a
// model says.


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
  "immunocompromised", "lupus", "crohn", "crohns", "deaf", "blind", "wheelchair", "disabled", "disability", "autism", "autistic", "adhd", "pill", "transplant", "sclerosis", "parkinson", "parkinsons",
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
  "nephew", "niece", "grandson", "granddaughter", "twins", "twin", "cousin", "toddler", "ella", "el", "usko",
]);
// Numbers said in words ("my daughter is three").
const HIGH_RISK_NUMBER_WORDS = new Set(("one two three four five six seven eight nine ten eleven twelve thirteen fourteen " +
  "fifteen sixteen seventeen eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred " +
  // Spanish and Hindi ("tres años", "paanch saal"); Hindi "do" (two) is left out: it is English "do".
  "uno dos tres cuatro cinco seis siete ocho nueve diez veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa ek teen char paanch chhe saat aath nau das bees pachaas assi").split(" "));

const isNumber = (w) => /^\d+$/.test(w) || HIGH_RISK_NUMBER_WORDS.has(w) || /^\d+yo$/.test(w);

/** The text states an allergy, a medication, a serious condition, a pregnancy or an age. */
function highRisk(text) {
  const words = wordsOf(text);
  const named = [ALLERGY_WORDS, MEDICATION_WORDS, CONDITION_WORDS, PREGNANCY_WORDS, AGE_STAGE_WORDS];
  if (words.some((w) => named.some((group) => group.has(w)))) return true;
  if (PREGNANCY_PHRASES.some(([a, b]) => words.some((w, i) => w === a && words[i + 1] === b))) return true;
  return words.some(isNumber) && words.some((w) => AGE_WORDS.has(w) || PERSON_WORDS.has(w));
}

module.exports = {
  BIRTH_WORDS,
  SELF_STATES,
  HAVING,
  MY,
  SELF_ATTRIBUTES,
  PLAN_VERBS,
  NOT_AGE_UNITS,
  AGE_WORDS,
  CHANGE_VERBS,
  TREATMENTS,
  ARTICLE_FILLERS,
  GENERIC_ROLES,
  HAVE_NOT,
  PLANS,
  LIFE_WORDS,
  NOT_TOLD,
  TELLING_VERBS,
  INSTRUCTIONS,
  INSTRUCTIONS_ANYWHERE_BY_FIRST,
  NOT_AN_OBJECT,
  NEEDS_AN_OBJECT,
  instructs,
  leadsAt,
  statesSelf,
  actsOnOwn,
  describesSelf,
  setsContext,
  tellsAboutCaller,
  tellsFacts,
  HIGH_RISK_FACT_TYPES,
  highRisk,
};
