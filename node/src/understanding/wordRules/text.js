"use strict";
// Text primitives the word rules share: words, stems, phrases, numbers, capitals.

const TRIM = "\\s!-\\/:-@\\[-`{-~";

const TRIM_EDGES = new RegExp(`^[${TRIM}]+|[${TRIM}]+$`, "g");

const WORDS = /[\p{L}\p{N}]+/gu;

// A phrase table keyed by first word, built once at load: a turn is then checked
// word by word against the few phrases that can start there.
function firstWords(phrases) {
  const index = new Map();
  for (const phrase of phrases) {
    if (!index.has(phrase[0])) index.set(phrase[0], []);
    index.get(phrase[0]).push(phrase);
  }
  return index;
}

// Whether any phrase of the table occurs in the turn (as `contains` on each, faster).
function hasPhrase(words, index) {
  for (let start = 0; start < words.length; start += 1) {
    for (const phrase of index.get(words[start]) || []) {
      if (startsWith(words, start, phrase)) return true;
    }
  }
  return false;
}

const POSSESSIVES = new Set(["my", "our", "mine", "ours"]);

// "My" in the other Latin-script languages callers use: Hinglish, French, Spanish,
// Portuguese, German, Italian, Dutch. Followed by a noun, the same rule as "my order".
// German "mein" is left out: in Hinglish it means "in" ("299 wale mein?").
const OTHER_POSSESSIVES = new Set([
  "humara", "humari", "humare", "hamare", "apna", "apni", "apne", "mai",
  "ma", "mon", "mes", "notre", "mi", "mis", "nuestro", "nuestra", "nuestros", "nuestras",
  "meu", "minha", "meus", "minhas", "nosso", "nossa", "meine", "meinen", "meinem",
  "meiner", "unser", "unsere", "mio", "mia", "miei", "mijn",
]);

// Whose a thing is: the caller's, or another person's ("her test results").
const OWNERS = new Set([...POSSESSIVES, ...OTHER_POSSESSIVES, "his", "her", "hers", "their", "theirs"]);

const FIRST_PERSON = new Set(["i", "me", "my", "mine", "myself", "we", "us", "our", "ours"]);

// After "can i", these ask for something for the caller ("can i get a refill of
// my prescription"), not how something is done.
const REQUEST_VERBS = new Set([
  "get", "have", "receive", "collect", "pick", "order", "book", "reserve", "renew",
  "refill", "extend", "claim", "redeem", "take",
]);

// A preposition-led utterance is a fragment only when nothing after it forms a
// clause: "for ten people" borrows its verb, "in python, how do i ..." brings one.
const CLAUSE_MARKERS = new Set([
  "what", "how", "why", "when", "where", "which", "who", "whose", "is", "are",
  "was", "were", "do", "does", "did", "can", "could", "should", "would", "will",
  "explain", "describe", "define", "list", "show", "tell", "give", "compare",
  "write", "summarise", "summarize", "translate",
]);

const FUNCTION_WORDS = new Set([
  "a", "about", "am", "an", "and", "any", "are", "as", "at", "be", "been",
  "but", "by", "can", "could", "did", "do", "does", "for", "from", "how",
  "i", "if", "in", "is", "it", "many", "me", "much", "my", "no", "not",
  "of", "ok", "okay", "on", "one", "or", "our", "please", "should", "so",
  "that", "the", "their", "them", "then", "there", "these", "they",
  "this", "those", "to", "us", "was", "were", "what", "whats", "when",
  "where", "which", "who", "why", "will", "with", "would", "you", "your",
]);

// Words that say how to choose, not what about: a turn made only of these and
// function words ("which is cheaper", "what do i do now") borrows its subject.
const BARE = new Set([
  "cheaper", "cheapest", "better", "best", "faster", "fastest", "quicker", "more",
  "less", "bigger", "smaller", "difference", "different", "same", "recommend",
  "prefer", "option", "options", "choice", "ones", "else", "other", "others",
  "between", "both", "either", "neither", "worth", "now", "next", "help", "good",
  "bad", "s", "d", "ll", "re", "ve", "m", "t",
]);

// Question words in front of a pronoun that are not what it refers to: "how long
// does it take" still needs the previous turn to say what "it" is.
const NON_REFERENTS = new Set([
  "long", "often", "far", "soon", "fast", "quickly", "early", "late",
  "exactly", "usually", "still", "also", "really", "actually",
]);

// After "that" or "those", these make it a pronoun rather than a determiner:
// "what does that cost", "is that refundable", as opposed to "that plan".
const PRONOUN_FOLLOWERS = new Set([
  "cost", "costs", "mean", "means", "take", "takes", "include", "includes",
  "cover", "covers", "work", "works", "apply", "applies", "last", "lasts",
  "come", "comes", "ship", "ships", "free", "available", "included",
  "possible", "refundable", "returnable", "right", "correct", "true", "safe",
  "worth", "enough", "extra", "cheaper", "better",
]);

// Who the caller is changes the answer ("as a premium member", "i'm a student",
// "i live in canada", "what plan am i on"), so such a turn is about this caller.
const CALLER_KINDS = new Set([
  "premium", "gold", "silver", "platinum", "diamond", "vip", "prime", "elite",
  "business", "businesses", "corporate", "enterprise", "wholesale", "student",
  "students", "senior", "seniors", "veteran", "veterans", "military", "teacher",
  "teachers", "employee", "employees", "member", "members", "subscriber",
  "subscribers", "partner", "partners", "reseller", "resellers", "pensioner",
  "pensioners", "retiree", "retirees", "nri",
]);
function normalise(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(TRIM_EDGES, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

// Comma-separated openers that say nothing about the question: "Hi there, quick question, ...".
const PREAMBLES = new Set([
  "hi", "hello", "hey", "hi there", "hello there", "hey there", "hmm", "um", "uh",
  "okay", "ok", "quick question", "a quick question", "well",
]); // not "so": a leading connective marks a follow-up

// The turn without leading comma-separated openers from PREAMBLES; unchanged when nothing else is left.
// shortcut: needs the commas, upgrade with the pluggable understander.
function stripPreamble(text) {
  let rest = String(text === null || text === undefined ? "" : text);
  for (;;) {
    const comma = rest.indexOf(",");
    if (comma < 0 || !PREAMBLES.has(normalise(rest.slice(0, comma))) || !rest.slice(comma + 1).trim()) return rest;
    rest = rest.slice(comma + 1).trimStart();
  }
}

function wordsOf(text) {
  const source = String(text === null || text === undefined ? "" : text).toLowerCase();
  return source.match(WORDS) || [];
}

// Words that change how a question is put, not what it asks about.
const FRAMING_WORDS = new Set([
  "what", "when", "where", "which", "who", "whom", "whose", "why", "you", "your", "yours",
  "we", "us", "tell", "know", "like", "want", "need", "help", "get", "got", "have", "has",
  "had", "give", "show", "find", "let", "would", "will", "may", "might", "must", "just",
  "also", "really", "kindly", "hi", "hello", "hey", "thanks", "thank", "question",
  "kya", "kab", "kahan", "kaise", "kaun", "kyun", "kyon", "kitna", "kitne", "kitni", "hai",
  "hain", "ho", "hun", "hoon", "aap", "tum", "ko", "ka", "ki", "ke", "se", "par", "bhi", "toh",
]);
function stem(word) {
  // "boxes", "dishes"; "prices" and "rates" just drop the "s". As in Python's _stem.
  if (word.endsWith("es") && /(s|x|z|ch|sh)$/.test(word.slice(0, -2)) && word.length >= 5) return word.slice(0, -2);
  for (const [suffix, keep] of [["ies", "y"], ["ing", ""], ["ed", ""], ["s", ""]]) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3 && !word.endsWith("ss")) {
      return word.slice(0, word.length - suffix.length) + keep;
    }
  }
  return word;
}

function contentWords(text) {
  return new Set(wordsOf(text).filter((w) => !FUNCTION_WORDS.has(w) && !FRAMING_WORDS.has(w)).map(stem));
}

function splitPlain(text) {
  return text.split(/\s+/).filter(Boolean);
}

function contains(words, phrase) {
  for (let start = 0; start + phrase.length <= words.length; start += 1) {
    let same = true;
    for (let offset = 0; offset < phrase.length; offset += 1) {
      if (words[start + offset] !== phrase[offset]) {
        same = false;
        break;
      }
    }
    if (same) return true;
  }
  return false;
}

// Things a caller owns; with a state word after them, a statement about their own item.
const OWNED_THINGS = new Set([
  "phone", "laptop", "headphones", "earphones", "charger", "shoes", "case", "tv",
  "television", "watch", "smartwatch", "device", "product", "item", "bag", "jacket",
  "shirt", "fridge", "refrigerator", "machine", "tablet", "camera", "speaker",
]);
const STATE_WORDS = new Set([
  "is", "are", "was", "were", "arrived", "came", "stopped", "broke", "broken", "not",
  "isn", "doesn", "won", "has", "got", "cracked", "damaged", "defective", "wrong",
  "missing", "stuck", "keeps",
]);
const GREETINGS = new Set(["hi", "hello", "hey", "namaste", "good", "morning", "afternoon", "evening"]);
const SPOKEN_DIGITS = new Set(["zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]);
const DIGIT_REPEATS = new Set(["double", "triple"]);
const ACTION_VERBS = new Set([
  "cancel", "book", "reschedule", "change", "update", "delete", "remove", "send", "text",
  "email", "call", "connect", "transfer", "escalate", "refund", "replace", "exchange",
  "return", "speak", "talk", "process", "block", "unblock", "check", "track", "add",
  "apply", "upgrade", "downgrade", "activate", "deactivate", "close", "open", "resend",
  "set", "remind", "schedule", "order", "buy", "pay", "play", "turn", "make", "put",
  "note", "save", "confirm", "reserve", "start", "stop", "create", "arrange", "register",
  "sign", "enrol", "enroll", "renew", "recharge", "pause", "resume", "mute", "wake",
  "dial", "message", "share", "forward", "submit", "file", "raise", "lodge", "report",
  "mark", "log", "bring", "get", "find", "go", "do",
]);
// Words in front of a clause that do not change what it is: "okay, book it".
const DISCOURSE = new Set([
  "please", "kindly", "just", "now", "so", "and", "then", "also", "okay", "ok",
  "alright", "fine", "great", "perfect", "sure", "yes", "yeah", "hey", "hi", "hello",
]);
// Replies to the agent, not questions: a reply word first, or an acknowledgement
// ("okay", "fine") not followed by a question, and no wh-question word anywhere.
const REPLY_LEADS = new Set([
  "yes", "yeah", "yep", "yup", "no", "nope", "nah", "correct", "exactly", "sure",
  // in the other languages callers use
  "oui", "si", "sí", "sim", "ja", "claro", "vale", "exacto", "exato", "certo", "nein", "não",
]);
const SOFT_REPLY_LEADS = new Set([
  "okay", "ok", "alright", "fine", "right", "great", "perfect", "cool", "awesome",
  "done", "deal", "lovely", "excellent", "haan", "theek", "accha", "acha",
]);
const QUESTION_LEADS = new Set([
  "can", "could", "do", "does", "did", "is", "are", "am", "was", "were", "will",
  "would", "should", "may", "shall", "has", "have", "tell", "explain", "describe",
]);
const WH_WORDS = new Set(["how", "what", "when", "where", "which", "who", "why"]);
// A statement told to the agent ("the iphone 16 is 10 rupees") is not a question
// whose answer other callers need, and what it asserts is the caller's to assert.
const STATEMENT_SUBJECTS = new Set([
  "the", "this", "that", "these", "those", "your", "its", "it", "a", "an", "his", "her", "their", "there",
]);
const SINGLE_WORDS = new Set([
  // live data
  "today", "tonight", "currently", "outage", "queue",
  // memory of this call
  "remember", "earlier",
  // dialogue and complaints
  "pardon", "louder", "slower", "slowly", "ridiculous", "frustrated", "frustrating",
  "angry", "upset", "worst", "terrible", "unacceptable", "disappointed",
  // steering
  "pretend", "ignore", "roleplay",
  // a crisis
  "suicide", "suicidal", "overdose", "overdosed", "unconscious", "collapsed",
  "bleeding", "choking", "fainted", "swallowed", "seizure", "drowning", "poisoned", "ambulance",
  // abuse
  "stupid", "idiot", "useless", "dumb", "shit", "damn", "hell", "crap", "fuck",
  "fucking", "bullshit", "bloody",
  // identity checks, and names given for anyone
  "otp", "cvv", "named", "surname", "mr", "mrs", "ms", "mister",
  // Hinglish possessives and first person
  "mera", "meri", "mere", "maine", "mujhe", "hamara", "hamari",
  // handing over to a person, Hinglish "I am"
  "supervisor", "hoon", "hun",
]);
// Advice that depends on the caller's own situation once they are in the turn:
// "can i take this medicine", not "what does a lawyer charge".
const SENSITIVE = new Set([
  "pregnancy", "pregnant", "breastfeeding", "allergic", "allergy", "allergies",
  "medicine", "medication", "dosage", "doctor", "symptoms", "sue", "lawsuit",
  "lawyer", "legal", "invest", "investment",
]);
const CLAUSES = /([,.!?;:]+)/;
// A caller's own health, legal trouble, abuse or money trouble. Told in the first
// person ("i'm pregnant", "my lawyer", "i have hiv"), a how-to after it does not
// make the turn general.
const MATTERS = new Set([
  // health
  "pregnant", "pregnancy", "breastfeeding", "allergic", "allergy", "allergies", "medicine",
  "medicines", "medication", "medications", "dosage", "dose", "doses", "doctor", "doctors",
  "symptoms", "symptom", "prescribed", "prescription", "diagnosed", "diagnosis", "hiv",
  "cancer", "tumour", "tumor", "diabetes", "diabetic", "asthma", "depression", "depressed",
  "anxiety", "surgery", "therapy", "chemotherapy", "chemo", "pill", "pills", "mg", "insulin",
  "disease", "illness", "sick", "infection", "injury", "injured", "pain", "nausea", "fever",
  "disability", "disabled", "psychiatrist", "therapist", "hospital", "stroke", "seizures",
  "epilepsy", "hepatitis", "miscarriage", "abortion", "rehab", "addiction", "addicted",
  "covid", "dementia", "alzheimer", "alzheimers", "wheelchair", "dialysis", "panic", "blind",
  "deaf", "apnea", "cpap", "pregnent", "pregant", "alergic", "alergy",
  // legal
  "lawyer", "lawyers", "attorney", "sue", "suing", "sued", "lawsuit", "court", "arrested",
  "arrest", "custody", "divorce", "convicted", "criminal", "bail", "jail", "prison", "deported",
  "police", "legal", "dui",
  // abuse
  "hit", "hits", "hitting", "beat", "beats", "beating", "abuse", "abused", "abusive", "assault",
  "assaulted", "raped", "threatens", "threatened", "violent", "violence", "stalking", "stalked",
  "harassed", "harassment", "bullied", "bullying",
  // money trouble and loss
  "debt", "debts", "owe", "bankrupt", "bankruptcy", "evicted", "eviction", "foreclosure",
  "unemployed", "fired", "afford", "overdue", "arrears", "homeless", "died", "death",
  "funeral", "deceased", "widowed", "widow", "passed",
]);
// Other people the caller speaks for: "for my wife", "my son was arrested".
const RELATIONS = new Set([
  "husband", "wife", "partner", "son", "daughter", "child", "children", "kid", "kids", "baby",
  "mother", "mom", "mum", "father", "dad", "brother", "sister", "parent", "parents",
  "boyfriend", "girlfriend", "fiance", "fiancee", "grandmother", "grandfather", "grandma",
  "grandpa", "uncle", "aunt", "nephew", "niece", "cousin", "family", "friend", "neighbour",
  "neighbor", "bhai", "didi", "behen",
]);
// Numbers that identify someone.
const ID_WORDS = new Set([
  "pin", "code", "otp", "order", "account", "card", "member", "membership", "policy",
  "ticket", "reference", "ref", "booking", "number", "id", "password", "passcode", "cvv",
  "pnr", "tracking", "invoice", "customer", "phone", "mobile", "ssn", "pan", "aadhaar",
  "passport", "licence", "license", "serial", "claim", "case", "transaction", "receipt",
  "born", "birth", "dob", "birthday", "postcode", "zip", "pincode", "iban", "ord", "flight",
  "seat", "room", "awb", "consignment", "docket", "nasci", "naci", "nací", "nacido", "nacida",
  "nascido", "nascida", "né", "née", "paida", "janam",
]);
// Amounts said about oneself ("i owe forty thousand"), not small counts ("can i get two").
const AMOUNT_WORDS = new Set([
  "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
  "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
  "ninety", "hundred", "thousand", "lakh", "lakhs", "crore", "million",
]);
const NUMBER_WORDS = new Set([...SPOKEN_DIGITS, ...DIGIT_REPEATS, ...AMOUNT_WORDS]);
const MONTHS = new Set([
  "january", "february", "march", "april", "may", "june", "july", "august", "september",
  "october", "november", "december", "jan", "feb", "apr", "jun", "jul", "aug", "sep",
  "sept", "oct", "nov", "dec",
]);
const ORDINALS = new Set([
  "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
  "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
  "seventeenth", "eighteenth", "nineteenth", "twentieth", "thirtieth",
]);
const STREET_WORDS = new Set([
  "street", "st", "road", "rd", "lane", "ln", "avenue", "ave", "drive", "boulevard", "blvd",
  "marg", "nagar", "colony", "sector", "apartments", "tower", "towers", "block", "society",
  "crescent", "terrace", "court", "place", "square", "highway", "calle", "rua", "rue",
  "avenida", "strasse", "straße", "plaza", "platz",
]);
const UNIT_WORDS = new Set(["flat", "apartment", "apt", "house", "unit", "plot", "suite", "door", "sector", "block"]);
const DECIMAL = /\p{Nd}/gu;
const HAS_DECIMAL = /\p{Nd}/u;
// Any script's digits: "４４０９", "٤٤٠٩".
function hasDigit(word) {
  return HAS_DECIMAL.test(word);
}

function amount(word) {
  return AMOUNT_WORDS.has(word) || (hasDigit(word) && word.match(DECIMAL).length >= 2);
}

// Whether any of words[from, to) passes `test`, without copying the slice.
function anyIn(words, from, to, test) {
  for (let index = Math.max(0, from); index < Math.min(to, words.length); index += 1) {
    if (test(words[index])) return true;
  }
  return false;
}

// Before a capitalised word, these make it a person: "for Rahul", "Dr Mehta",
// "does Mohit have".
const NAME_SLOTS = new Set(["for", "dr", "prof", "sir", "madam", "miss", "shri", "smt"]);
const TITLES = new Set([...NAME_SLOTS].filter((w) => w !== "for"));
const AUXILIARIES = new Set(["can", "could", "does", "did", "is", "has", "had", "will", "would", "should", "may", "was"]);
// After a name, what a person does: "Priya called", "Arjun Mehta checked in".
const NAME_VERBS = new Set([
  "has", "have", "had", "called", "calls", "said", "says", "told", "wants", "needs", "checked",
  "booked", "ordered", "paid", "sent", "asked", "pick", "picks", "collect", "collects", "come",
  "comes", "coming", "get", "gets", "speak", "talk",
]);
// After a name in Hinglish, these make it a place, a festival or a thing: "Durga Puja
// mein", "Patna ka". "<name> ka order" is a person's, found in lower case below.
const POSTPOSITIONS = new Set(["mein", "me", "pe", "par", "ka", "ki", "ke", "se", "wala", "wale", "wali", "main", "tak"]);
const PLACE_PREPOSITIONS = new Set([
  "to", "in", "at", "from", "near", "into", "via", "across", "around", "within", "on", "en", "em", "au", "aux",
]);
// A name only matters next to a person's own business or a person's action: "is the
// order for Rahul ready", "Dr. Iyer told me to call you". "Do you ship to Hong Kong",
// "what's the McDonald's breakfast time" name places and brands.
const PERSONAL_MATTERS = new Set([
  "account", "accounts", "order", "orders", "booking", "bookings", "appointment", "appointments",
  "parcel", "parcels", "package", "delivery", "refund", "refunds", "bill", "bills", "invoice",
  "ticket", "tickets", "prescription", "reservation", "reservations", "subscription",
  "payment", "balance", "card", "loan", "claim", "statement", "shipment", "table", "room",
]);
const PERSON_CUES = new Set([
  "call", "called", "calling", "tell", "told", "said", "says", "ask", "asked", "speak",
  "speaking", "talk", "available", "pick", "collect", "wants", "needs", "coming", "arrived",
  "booked", "ordered", "paid", "sent", "holder", "here", "birthday", "checked",
]);
const ROLES = new Set([
  "someone", "somebody", "anyone", "anybody", "agent", "human", "person", "manager",
  "representative", "operator", "sales", "billing", "accounts", "department", "reception",
  "front", "staff", "engineer", "technician", "executive", "advisor", "adviser", "officer",
]);
// Capitalised words that are not names: days, months, holidays, plan tiers and the
// common nouns of product names ("Apple Pay", "Google Maps").
const COMMON_CAPITALS = new Set([
  "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mondays",
  "tuesdays", "wednesdays", "thursdays", "fridays", "saturdays", "sundays", "christmas",
  "easter", "diwali", "eid", "holi", "thanksgiving", "new", "year", "years", "eve", "black",
  "cyber", "basic", "standard", "pro", "plus", "max", "mini", "lite", "ultra", "free",
  "starter", "maps", "map", "store", "app", "apps", "cloud", "music", "tv", "wallet", "bank",
  "mail", "watch", "pad", "book", "air", "home", "assistant", "plan", "plans", "support",
  "service", "services", "care", "team", "help", "desk", "center", "centre", "express",
  "airport", "station", "mall", "market", "city", "park", "international", "airlines",
  "insurance", "life", "health", "energy", "fiber", "fibre", "broadband", "internet",
  "wifi", "english", "hindi", "spanish", "french", "german", "terms", "conditions",
  "privacy", "policy", "hello", "hi", "thanks", "thank", "please", "okay", "sorry", "wi", "fi",
  "office", "checkout", "eats",
]);
const KNOWN_WORDS = new Set(
  [
    COMMON_CAPITALS, FUNCTION_WORDS, ACTION_VERBS, CALLER_KINDS, OWNED_THINGS, STATE_WORDS,
    MATTERS, RELATIONS, ID_WORDS, NUMBER_WORDS, MONTHS, ORDINALS, STREET_WORDS, UNIT_WORDS,
    GREETINGS, DISCOURSE, REPLY_LEADS, SOFT_REPLY_LEADS, QUESTION_LEADS, WH_WORDS, SINGLE_WORDS,
    SENSITIVE, BARE, NON_REFERENTS, PRONOUN_FOLLOWERS, CLAUSE_MARKERS, REQUEST_VERBS,
    STATEMENT_SUBJECTS, [...OWNERS].filter((w) => !OTHER_POSSESSIVES.has(w)), FIRST_PERSON, AUXILIARIES,
  ].flatMap((set) => [...set])
);

// A name, given by the caller or about anyone, in an introduction or as a proper noun.
// Not a word these rules know, nor shaped like a verb or an adjective: maybe a name.
function unknown(word) {
  return !KNOWN_WORDS.has(word) && !ROLES.has(word) && !/(ing|ed|ly)$/.test(word);
}

// The last character before `index` that is not whitespace, or "" at the start.
function charBefore(text, index) {
  for (let at = index - 1; at >= 0; at -= 1) {
    if (!/\s/.test(text[at])) return text[at];
  }
  return "";
}

function isUpper(text) {
  return text === text.toUpperCase() && text !== text.toLowerCase();
}

function capitalised(word) {
  return isUpper([...word][0]) && !isUpper(word);
}

// A capitalised name (one word, or two in a row) in a person's place: after a title
// ("Dr. Iyer"), before what a person does ("Priya called", "does Mohit have an
// appointment"), or after one of the caller's own matters ("the order for Rahul").
// Followed by a Hinglish postposition it is a place or a festival ("Durga Puja mein").
function capitalisedName(text, words) {
  const tokens = [...text.matchAll(WORDS)];
  if (tokens.length !== words.length) return false; // tokenisation disagrees (exotic case folding); other rules still apply
  let firstMatter = words.findIndex((w) => PERSONAL_MATTERS.has(w));
  if (firstMatter < 0) firstMatter = words.length;
  const personal = firstMatter < words.length || words.some((w) => PERSON_CUES.has(w));
  for (let index = 0; index < tokens.length; index += 1) {
    const match = tokens[index];
    if (!capitalised(match[0]) || KNOWN_WORDS.has(words[index])) continue;
    const lead = index > 0 ? words[index - 1] : "";
    if (TITLES.has(lead)) return true; // a title, with or without its period: "Dr. Iyer"
    let end = index + 1;
    if (
      end < tokens.length && /^\s+$/.test(text.slice(match.index + match[0].length, tokens[end].index)) &&
      capitalised(tokens[end][0])
    ) {
      if (KNOWN_WORDS.has(words[end])) continue; // "Apple Pay", "Google Maps"
      end += 1;
    }
    const after = end < words.length ? words[end] : "";
    if (POSTPOSITIONS.has(after)) continue;
    if (NAME_VERBS.has(after) && personal) return true;
    if (firstMatter < index && !PLACE_PREPOSITIONS.has(lead)) return true;
  }
  return false;
}

function startsWith(words, at, phrase) {
  return phrase.every((w, k) => words[at + k] === w);
}

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function flatten(text) {
  return wordsOf(text).join("");
}

// Runs of digits that belong together ("555 0199", "1800-555-0100", "99,812") make one number.
const NUMBER_RUN = /[0-9]+(?:[ ,\-./][0-9]+)*/g;
const isDecimalWord = (word) => /\p{Nd}/u.test(word);
const startsUpper = (word) => /^\p{Lu}/u.test(word);

function numbersOf(text) {
  return (String(text || "").match(NUMBER_RUN) || []).map((run) => run.replace(/[^0-9]/g, ""));
}

// Words capitalised mid-sentence ("... my agent Priya said"), lower-cased.
function properNouns(text) {
  const found = new Set();
  const source = String(text || "");
  for (const match of source.matchAll(WORDS)) {
    const word = match[0];
    const before = source.slice(0, match.index).trimEnd() || ".";
    if (word[0] !== word[0].toLowerCase() && word !== "I" && !".!?".includes(before[before.length - 1])) {
      found.add(word.toLowerCase());
    }
  }
  return found;
}

// Words a request opens with before what it asks: "please", "can you".
const REQUEST_OPENERS = new Set([...DISCOURSE, "can", "could", "will", "would", "you", "kindly"]);

// Each clause's words from where its request starts: "Okay, can you answer in Spanish"
// gives ["answer", "in", "spanish"].
function clauseStarts(text) {
  const starts = [];
  for (const clause of String(text).split(CLAUSES)) {
    let words = wordsOf(clause);
    while (words.length && REQUEST_OPENERS.has(words[0])) words = words.slice(1);
    if (words.length) starts.push(words);
  }
  return starts;
}

// Word and phrase tables more than one theme of the word rules reads.


const CONTEXT_BOUND_THRESHOLD = 0.995;

// How a cached answer that commits the business (a price, a refund, a policy)
// may be spoken. Only matters when the server's decision engine flags one.
const COMMITMENTS = {
  serve: () => true,
  exact: (hit) => Boolean(hit.exact),
  never: () => false,
};

const CONNECTIVES = new Set(["and", "so", "but", "or", "also", "then", "aur", "phir", "lekin", "toh"]);

// Which question a shared answer was saved for, kept beside it as a plain key (keyed by the
// answer, per tenant), so a hit can be checked against the question it really answers. A
// plain GET/SET key, not the tool cache: that is an Enterprise feature.
const QUESTIONS_KEPT = 8;
// How long a question record lives when the answer has no TTL of its own.
const QUESTION_TTL = 30 * 24 * 3600;

const EMAIL_ENDINGS = new Set(["com", "in", "org", "net", "co", "io"]);
// After these leads, an action verb is a request for the agent to do something.
const ACTION_LEADS = [
  ["please"], ["can", "you"], ["could", "you"], ["will", "you"], ["would", "you"],
  ["i", "want", "to"], ["i", "d", "like", "to"], ["i", "would", "like", "to"],
  ["i", "need", "to"], ["let", "me"], ["i", "wanna"],
];
const ACTION_LEADS_BY_FIRST = firstWords(ACTION_LEADS);
// A crisis, said in words: private, and what follows it stays with it.
const CRISIS_PHRASES = [
  ["end", "it", "all"], ["kill", "myself"], ["hurt", "myself"], ["harm", "myself"],
  ["want", "to", "die"], ["self", "harm"], ["end", "my", "life"], ["take", "my", "life"],
  ["reason", "to", "live"], ["better", "off", "dead"], ["not", "breathing"], ["heart", "attack"],
  ["ending", "my", "life"], ["ending", "it", "all"], ["end", "myself"], ["kill", "me"],
  ["panic", "attack"], ["wanna", "die"],
];
// Digits read out in groups: "4 4 0 9", "98 765 43". Commas and points are left
// out, so a price ("1,499") or a weight ("1.5") is not an identifier.
const SPACED_DIGITS = /[0-9]+(?:[ \t-]+[0-9]+)+/g;
const THIRD_PERSON = new Set(["he", "she", "him", "her", "his", "hers", "their", "theirs"]);
// One named person the caller speaks about ("wife has diabetes", "she is pregnant"),
// not a kind of person ("a family lawyer").
const SOMEONE = new Set([...RELATIONS, ...THIRD_PERSON]);
for (const kind of [
  "family", "friend", "partner", "children", "kids", "kid", "child", "parent", "parents", "baby",
  "neighbour", "neighbor", "cousin", "their", "theirs",
]) SOMEONE.delete(kind);
// A follow-up this short, after an emergency or a medical turn, is about it.
const FOLLOW_UP_WORDS = 8;
const URGENT = new Set([
  ...MATTERS,
  "suicide", "suicidal", "overdose", "overdosed", "unconscious", "collapsed", "bleeding",
  "choking", "fainted", "swallowed", "seizure", "drowning", "poisoned", "ambulance",
  "breathing", "fire", "emergency", "cpr",
]);

// What the server puts in a stored answer in place of a caller's detail (its PII scrubber):
// "pii_email_k3fa9". Spoken, it is noise at best. As in Python.
const PII_PLACEHOLDER = /(?<![A-Za-z0-9_])pii_(?:email|phone|natid|card|person|location|ip|dob|passport|iban)_[A-Za-z0-9]+/i;

// A caller turn that tries to change what the model says for the rest of the call.
const STEERING = [
  ["pretend"], ["from", "now", "on"], ["for", "this", "call"], ["for", "the", "rest"],
  ["ignore"], ["forget"], ["act", "as"], ["you", "are", "now"], ["assume"],
  ["always", "say"], ["tell", "everyone"], ["roleplay"], ["role", "play"],
];

module.exports = {
  stripPreamble,
  TRIM,
  TRIM_EDGES,
  WORDS,
  firstWords,
  hasPhrase,
  POSSESSIVES,
  OTHER_POSSESSIVES,
  OWNERS,
  FIRST_PERSON,
  REQUEST_VERBS,
  CLAUSE_MARKERS,
  FUNCTION_WORDS,
  BARE,
  NON_REFERENTS,
  PRONOUN_FOLLOWERS,
  CALLER_KINDS,
  normalise,
  wordsOf,
  FRAMING_WORDS,
  stem,
  contentWords,
  splitPlain,
  contains,
  OWNED_THINGS,
  STATE_WORDS,
  GREETINGS,
  SPOKEN_DIGITS,
  DIGIT_REPEATS,
  ACTION_VERBS,
  DISCOURSE,
  REPLY_LEADS,
  SOFT_REPLY_LEADS,
  QUESTION_LEADS,
  WH_WORDS,
  STATEMENT_SUBJECTS,
  SINGLE_WORDS,
  SENSITIVE,
  CLAUSES,
  MATTERS,
  RELATIONS,
  ID_WORDS,
  AMOUNT_WORDS,
  NUMBER_WORDS,
  MONTHS,
  ORDINALS,
  STREET_WORDS,
  UNIT_WORDS,
  DECIMAL,
  HAS_DECIMAL,
  hasDigit,
  amount,
  anyIn,
  NAME_SLOTS,
  TITLES,
  AUXILIARIES,
  NAME_VERBS,
  POSTPOSITIONS,
  PLACE_PREPOSITIONS,
  PERSONAL_MATTERS,
  PERSON_CUES,
  ROLES,
  COMMON_CAPITALS,
  KNOWN_WORDS,
  unknown,
  charBefore,
  isUpper,
  capitalised,
  capitalisedName,
  startsWith,
  escapeRegExp,
  flatten,
  NUMBER_RUN,
  isDecimalWord,
  startsUpper,
  numbersOf,
  properNouns,
  REQUEST_OPENERS,
  clauseStarts,
  CONTEXT_BOUND_THRESHOLD,
  COMMITMENTS,
  CONNECTIVES,
  QUESTIONS_KEPT,
  QUESTION_TTL,
  EMAIL_ENDINGS,
  ACTION_LEADS,
  ACTION_LEADS_BY_FIRST,
  CRISIS_PHRASES,
  SPACED_DIGITS,
  THIRD_PERSON,
  SOMEONE,
  FOLLOW_UP_WORDS,
  URGENT,
  PII_PLACEHOLDER,
  STEERING,
};
