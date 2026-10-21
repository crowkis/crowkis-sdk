"use strict";

const crypto = require("node:crypto");
const { Agent, voiceAddonMissing, _storeLater: storeLater } = require("./agent.js");
const { CrowkisClient } = require("./index.js");

// The server takes at most this per count in one report.
const REPORT_MAX = 1000000;

const TRIM = "\\s!-\\/:-@\\[-`{-~";

const TRIM_EDGES = new RegExp(`^[${TRIM}]+|[${TRIM}]+$`, "g");

const WORDS = /[\p{L}\p{N}]+/gu;

const SLOT = /\{([^{}\s]+)\}/g;

const CONTEXT_BOUND_THRESHOLD = 0.995;

// Text written for a screen: a link, code, or markup a voice would read out.
const UNSPEAKABLE = /https?:\/\/|www\.|`|\]\(|\*\*|^\s*(?:#{1,6}\s|\|)/im;

// How a cached answer that commits the business (a price, a refund, a policy)
// may be spoken. Only matters when the server's decision engine flags one.
const COMMITMENTS = {
  serve: () => true,
  exact: (hit) => Boolean(hit.exact),
  never: () => false,
};

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

function speakable(text) {
  return !UNSPEAKABLE.test(text || "");
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

const PROCEDURAL = [
  ["how", "do", "i"],
  ["how", "do", "we"],
  ["how", "to"],
  ["how", "can", "i"],
  ["how", "can", "we"],
  ["steps", "to"],
  ["where", "do", "i"],
  ["can", "i"],
  ["can", "we"],
  ["is", "there", "a", "way"],
  ["walk", "me", "through"],
  ["help", "me"],
  ["guide"],
  ["tutorial"],
  ["what", "should", "i", "do"],
  ["what", "do", "i", "do"],
  ["what", "can", "i", "do"],
  ["what", "are", "the", "steps"],
  ["how", "long", "do", "i", "have"],
  ["what", "is", "the", "process"],
  ["what", "happens", "if"],
  ["what", "should", "i", "bring"],
  ["what", "should", "i", "expect"],
  ["what", "should", "i", "prepare"],
  ["what", "should", "i", "ask"],
  ["what", "do", "i", "need", "to", "bring"],
];
const PROCEDURAL_BY_FIRST = firstWords(PROCEDURAL);
// After "main", these make it the English adjective: "main branch", "main menu".
const MAIN_THINGS = new Set([
  "branch", "office", "gate", "entrance", "menu", "road", "door", "store", "page", "course",
  "difference", "reason", "line", "station", "building", "counter", "desk", "hall", "lobby",
  "street", "market", "square", "campus", "hospital", "website", "app", "screen", "number",
  "feature", "features", "plan", "dish", "event", "stage", "switch", "power",
]);

// After "can i", these ask for something for the caller ("can i get a refill of
// my prescription"), not how something is done.
const REQUEST_VERBS = new Set([
  "get", "have", "receive", "collect", "pick", "order", "book", "reserve", "renew",
  "refill", "extend", "claim", "redeem", "take",
]);

const OWNER_PREPOSITIONS = new Set([
  "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
  "onto", "under", "via",
]);

const STATE_LEADS = new Set([
  "what", "whats", "when", "where", "which", "who", "how", "is", "are",
  "has", "have", "had", "did", "do", "does", "show", "tell", "check",
  "status",
]);

const CONNECTIVES = new Set(["and", "so", "but", "or", "also", "then", "aur", "phir", "lekin", "toh"]);

const CONNECTIVE_PAIRS = new Set(["what about", "how about", "ok and", "okay and"]);

const ELLIPSIS_LEADS = new Set([
  "for", "with", "about", "in", "on", "at", "to", "from", "by",
]);

// A preposition-led utterance is a fragment only when nothing after it forms a
// clause: "for ten people" borrows its verb, "in python, how do i ..." brings one.
const CLAUSE_MARKERS = new Set([
  "what", "how", "why", "when", "where", "which", "who", "whose", "is", "are",
  "was", "were", "do", "does", "did", "can", "could", "should", "would", "will",
  "explain", "describe", "define", "list", "show", "tell", "give", "compare",
  "write", "summarise", "summarize", "translate",
]);

// Shapes that borrow their subject from the previous turn.
const FOLLOW_UP_PHRASES = [
  ["same", "for"], ["the", "same"], ["what", "else"], ["anything", "else"], ["tell", "me", "more"],
  ["which", "one"], ["instead"],
];
const FOLLOW_UP_PHRASES_BY_FIRST = firstWords(FOLLOW_UP_PHRASES);
const FOLLOW_UP_ENDINGS = new Set(["too", "also", "instead"]);

const ANAPHOR_PHRASES = ["this one", "the second one", "the first one", "the other one"];

const ANAPHORS = new Set([
  "that", "those", "it", "them", "they", "these", "this", "he", "she", "him", "her", "his", "hers", "their",
]);

const DEMONSTRATIVES = new Set(["that", "those", "these", "this"]);

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
const CALLER_LEADS = [["as", "a"], ["as", "an"], ["i", "am"], ["i", "m"]];
const SELF_PHRASES = [
  ["am", "i"], ["do", "i", "qualify"], ["i", "live", "in"], ["i", "am", "from"],
  ["i", "m", "from"], ["i", "am", "based"], ["i", "m", "based"], ["i", "am", "on"],
  ["i", "m", "on"], ["i", "live", "on"], ["i", "live", "at"], ["i", "stay", "in"], ["i", "stay", "at"],
  ["i", "m", "staying"], ["i", "am", "staying"],
];
const SELF_PHRASES_BY_FIRST = firstWords(SELF_PHRASES);

function describesCaller(words) {
  if (hasPhrase(words, SELF_PHRASES_BY_FIRST)) return true;
  // "for business accounts, what ..." frames the turn; "the grace period for
  // premium payment" only names a kind of thing.
  if (words[0] === "for" && words.slice(1, 4).some((w) => CALLER_KINDS.has(w))) return true;
  // "what discount do you have for pensioners like me"
  if (words.some((w) => CALLER_KINDS.has(w)) && (contains(words, ["like", "me"]) || contains(words, ["like", "us"]))) {
    return true;
  }
  for (let index = 0; index < words.length; index += 1) {
    for (const lead of CALLER_LEADS) {
      const end = index + lead.length;
      if (lead.every((w, k) => words[index + k] === w) && words.slice(end, end + 3).some((w) => CALLER_KINDS.has(w))) {
        return true;
      }
    }
  }
  return false;
}

function normalise(text) {
  return String(text === null || text === undefined ? "" : text)
    .replace(TRIM_EDGES, "")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .join(" ");
}

function wordsOf(text) {
  const source = String(text === null || text === undefined ? "" : text).toLowerCase();
  return source.match(WORDS) || [];
}

// Which question a shared answer was saved for, kept beside it as a plain key (keyed by the
// answer, per tenant), so a hit can be checked against the question it really answers. A
// plain GET/SET key, not the tool cache: that is an Enterprise feature.
const QUESTIONS_KEPT = 8;
// Words that change how a question is put, not what it asks about.
const FRAMING_WORDS = new Set([
  "what", "when", "where", "which", "who", "whom", "whose", "why", "you", "your", "yours",
  "we", "us", "tell", "know", "like", "want", "need", "help", "get", "got", "have", "has",
  "had", "give", "show", "find", "let", "would", "will", "may", "might", "must", "just",
  "also", "really", "kindly", "hi", "hello", "hey", "thanks", "thank", "question",
]);

function stem(word) {
  for (const [suffix, keep] of [["ies", "y"], ["ing", ""], ["ed", ""], ["es", ""], ["s", ""]]) {
    if (word.endsWith(suffix) && word.length - suffix.length >= 3) return word.slice(0, word.length - suffix.length) + keep;
  }
  return word;
}

function contentWords(text) {
  return new Set(wordsOf(text).filter((w) => !FUNCTION_WORDS.has(w) && !FRAMING_WORDS.has(w)).map(stem));
}

// Two questions about different things: each has content words the other does not ("on
// Saturday" / "on Sunday"). A rewording only adds or drops words on one side, or changes
// how it asks ("can I" / "do I"). Same as Python's _different_specifics.
function differentSpecifics(asked, stored) {
  const a = contentWords(asked);
  const s = contentWords(stored);
  return [...a].some((w) => !s.has(w)) && [...s].some((w) => !a.has(w));
}

function questionKey(tenant, answer) {
  const digest = crypto.createHash("sha256").update(String(answer).trim(), "utf8").digest("hex").slice(0, 32);
  return `crowkis:question:${tenant || "default"}:${digest}`;
}

const tenantOf = (agent) => (agent && (agent.tenant || (agent.client && agent.client.tenant))) || null;

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

// Where the turn names something of the caller's or of another person's:
// "my food", "her test results", "our usual table".
function ownedRecordAt(words) {
  for (let index = 0; index + 1 < words.length; index += 1) {
    if (OWNERS.has(words[index]) && !FUNCTION_WORDS.has(words[index + 1])) return index;
  }
  // Hinglish "main order kab aayega"; English "main" only ever leads a question
  // through a question word ("what is the main difference").
  if (
    words[0] === "main" && words.length > 1 && !FUNCTION_WORDS.has(words[1]) && !MAIN_THINGS.has(words[1]) &&
    !words.some((w) => WH_WORDS.has(w))
  ) {
    return 0;
  }
  return -1;
}

function procedural(words) {
  for (let start = 0; start < words.length; start += 1) {
    for (const phrase of PROCEDURAL_BY_FIRST.get(words[start]) || []) {
      if (!startsWith(words, start, phrase)) continue;
      if (phrase[0] === "can" && REQUEST_VERBS.has(words[start + phrase.length])) continue;
      return true;
    }
  }
  return false;
}

// "Can i get ...", "could we book ...": the caller asks for something for themselves.
function requests(words) {
  for (let index = 0; index + 2 < words.length; index += 1) {
    if (
      ["can", "could", "may"].includes(words[index]) &&
      ["i", "we"].includes(words[index + 1]) &&
      REQUEST_VERBS.has(words[index + 2])
    ) {
      return true;
    }
  }
  return false;
}

function isStateInterrogative(words) {
  return STATE_LEADS.has(words[0]) || words.includes("status");
}

// --- Turns whose answer must never be shared ------------------------------------------
// Kept word for word with the Python SDK (voice.py). Each group fails closed: a
// match means "answer fresh, never cache".

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
const INTRO_AFTER_GREETING = [["i", "am"], ["i", "m"], ["this", "is"], ["it", "s"], ["my", "name"]];
const SPOKEN_DIGITS = new Set(["zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"]);
const DIGIT_REPEATS = new Set(["double", "triple"]);
const EMAIL_ENDINGS = new Set(["com", "in", "org", "net", "co", "io"]);
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
// A verb first is a request only when it acts on something ("set a timer", "turn
// off the lights", "cancel my order"). A verb before a noun is search-style
// phrasing: "refund status for john", "return policy for shoes".
const ACTION_OBJECTS = new Set([
  ...FUNCTION_WORDS,
  "a", "an", "some", "another", "all", "everything", "up", "off", "out", "down", "over",
  "back", "away", "ahead", "his", "her", "our", "my", "me", "us",
]);
for (const subject of ["you", "i", "we", "they"]) ACTION_OBJECTS.delete(subject); // "do you ship abroad" asks, "do it" tells
// After these leads, an action verb is a request for the agent to do something.
const ACTION_LEADS = [
  ["please"], ["can", "you"], ["could", "you"], ["will", "you"], ["would", "you"],
  ["i", "want", "to"], ["i", "d", "like", "to"], ["i", "would", "like", "to"],
  ["i", "need", "to"], ["let", "me"], ["i", "wanna"],
];
const ACTION_LEADS_BY_FIRST = firstWords(ACTION_LEADS);
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
const STATEMENT_VERBS = new Set(["is", "are", "was", "were", "s", "costs", "cost", "means", "includes", "has", "have"]);
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
// A crisis, said in words: private, and what follows it stays with it.
const CRISIS_PHRASES = [
  ["end", "it", "all"], ["kill", "myself"], ["hurt", "myself"], ["harm", "myself"],
  ["want", "to", "die"], ["self", "harm"], ["end", "my", "life"], ["take", "my", "life"],
  ["reason", "to", "live"], ["better", "off", "dead"], ["not", "breathing"], ["heart", "attack"],
  ["ending", "my", "life"], ["ending", "it", "all"], ["end", "myself"], ["kill", "me"],
  ["panic", "attack"], ["wanna", "die"],
];
const CRISIS_PHRASES_BY_FIRST = firstWords(CRISIS_PHRASES);

// An emergency or a crisis, in the languages callers use (English, Hindi/Hinglish,
// Spanish, Portuguese, French), found by its shape rather than by fixed sentences.
// Word starts that are always one: "suicidal", "overdosed", "behosh", "desmayó".
const EMERGENCY_STEMS = [
  "suicid", "overdos", "sobredos", "envenen", "behosh", "unconscious", "inconscien", "desmay",
  "desmai", "évanoui", "evanoui", "fainted", "collapsed", "convuls", "seizure", "choking",
  "atragant", "engasg", "étouff", "drowning", "ahogand", "afogand", "bleeding", "sangrand",
  "khudkushi", "aatmahatya", "atmahatya", "infarto", "poisoned", "poisoning", "electrocut",
];
const EMERGENCY_PHRASES = [
  ["heart", "attack"], ["not", "breathing"], ["no", "respira"], ["não", "respira"], ["nao", "respira"],
  ["ne", "respire"], ["saans", "nahi"], ["saans", "nahin"], ["dil", "ka", "daura"], ["crise", "cardiaque"],
  ["chest", "pain"], ["dolor", "de", "pecho"], ["dor", "no", "peito"], ["seene", "mein", "dard"],
  ["cut", "myself"], ["cutting", "myself"], ["hurt", "myself"], ["hurting", "myself"],
  ["harm", "myself"], ["harming", "myself"], ["burn", "myself"], ["burned", "myself"],
  ["me", "corté"], ["me", "corte"], ["me", "corto"], ["me", "cortei"], ["me", "cortar"],
  ["me", "matar"], ["me", "mato"], ["me", "tuer"], ["me", "couper"], ["khud", "ko"],
  ["cortarme"], ["matarme"], ["lastimarme"], ["suicidarme"], ["having", "a", "stroke"],
  ["had", "a", "stroke"], ["khoon", "nikal"],
];
const EMERGENCY_PHRASES_BY_FIRST = firstWords(EMERGENCY_PHRASES);
// A wish to die ("i want to die", "quiero morir", "marna chahta hoon"), or not to
// live ("i don't want to live anymore", "jeena nahi chahta"), in any word order.
const WANTS = new Set(["want", "wanna", "going", "gonna", "quiero", "quero", "veux", "voudrais", "chahta", "chahti", "chahte", "ganas"]);
const DYING = new Set(["die", "dying", "morir", "morirme", "morrer", "mourir", "marna", "marne", "maut"]);
const LIVING = new Set(["live", "living", "vivir", "viver", "vivre", "jeena", "jeene", "jina"]);
const NEGATIONS = new Set(["don", "dont", "not", "no", "never", "não", "nao", "ne", "nahi", "nahin", "na"]);
// Harm turned on oneself, in any form: "cutting myself", "she keeps harming herself".
const HARMS = ["cut", "hurt", "harm", "kill", "burn", "stab", "starv", "hang", "poison"];
const REFLEXIVES = new Set(["myself", "herself", "himself", "themselves", "ourselves", "yourself"]);
// Something swallowed or drunk that must not be: "mere bete ne kerosene pee liya".
const SUBSTANCES = new Set([
  "kerosene", "kerosine", "bleach", "pesticide", "insecticide", "poison", "acid", "phenyl",
  "phenol", "detergent", "veneno", "lejía", "lejia", "cloro", "javel", "battery", "batteries",
  "pila", "pilas", "bateria", "baterias", "pills", "tablets", "pastillas", "pastilhas",
  "comprimidos", "cachets", "goli", "goliyan", "dawai",
]);
const INGESTED = new Set([
  "swallowed", "swallow", "swallowing", "drank", "drunk", "ate", "eaten", "took", "taken",
  "ingested", "pee", "piya", "pi", "peeli", "kha", "khaa", "khali", "khaya", "nigal", "nigla",
  "nigli", "tragó", "trago", "tragado", "tragada", "bebió", "bebio", "tomó", "comió", "comio",
  "engoliu", "engoli", "bebeu", "tomou", "comeu", "avalé", "avale", "bu", "mangé",
]);
// Hurt, or attacked, said of someone: "bhai ka accident ho gaya", "my dad fell".
const INJURIES = new Set([
  "accident", "accidente", "acidente", "burn", "burned", "burnt", "quemado", "quemada", "quemó",
  "queimou", "queimado", "brûlé", "fracture", "fractured", "fractura", "fratura", "injured",
  "hurt", "herido", "herida", "ferido", "ferida", "blessé", "blessée", "bitten", "mordido",
  "stabbed", "shot", "chot", "fell", "gir", "gira", "giri", "gire", "caí", "cayó", "caiu", "tombé",
  "assaulted", "assault", "attacked", "mugged", "beaten", "agredido", "agredida", "agrediu",
  "agressé", "agressée", "golpeó", "golpearon", "maara", "maari", "peeta", "peeti",
]);
// Who or when: the event happened to someone ("ho gaya", "my", "papa", "she").
const EVENT_MARKERS = new Set([
  "ho", "gaya", "gayi", "gaye", "hua", "hui", "happened", "had", "met", "got", "was", "were",
  "i", "me", "my", "we", "our", "he", "she", "his", "her", "him", "they", "mera", "meri",
  "mere", "mujhe", "yo", "mi", "eu", "meu", "minha", "mon", "ma", "je", "tuvo", "teve",
  "papa", "mummy", "mom", "mum", "dad", "beta", "beti", "bete", "bhai", "behen", "didi",
]);

// An emergency or a crisis: self-harm, poisoning, injury, collapse, heart or assault.
function urgent(words) {
  if (hasPhrase(words, CRISIS_PHRASES_BY_FIRST) || hasPhrase(words, EMERGENCY_PHRASES_BY_FIRST)) return true;
  if (words.some((w) => EMERGENCY_STEMS.some((stem) => w.startsWith(stem)))) return true;
  if (words.some((w, i) => REFLEXIVES.has(w) && words.slice(Math.max(0, i - 2), i).some((v) => HARMS.some((h) => v.startsWith(h))))) {
    return true;
  }
  if (words.some((w) => SUBSTANCES.has(w)) && words.some((w) => INGESTED.has(w))) return true;
  if (words.some((w) => INJURIES.has(w)) && words.some((w) => EVENT_MARKERS.has(w) || RELATIONS.has(w))) return true;
  for (let index = 0; index < words.length; index += 1) {
    const near = words.slice(index, index + 4);
    if (near.some((w) => WANTS.has(w)) && near.some((w) => DYING.has(w))) return true;
    const wider = words.slice(index, index + 6);
    if (
      wider.some((w) => NEGATIONS.has(w)) && wider.some((w) => WANTS.has(w)) &&
      wider.some((w, at) => LIVING.has(w) && ((w !== "live" && w !== "living") || (at > 0 && wider[at - 1] === "to"))) // not "live chat"
    ) {
      return true;
    }
  }
  return false;
}
const NEVER_PHRASES = [
  // self-introduction, or anyone's name
  ["my", "name"], ["name", "s"], ["call", "me"], ["i", "m", "called"], ["name", "is"],
  ["name", "was"], ["names", "are"], ["is", "called"], ["was", "called"],
  // memory of this call
  ["did", "i"], ["i", "told", "you"], ["as", "i", "said"], ["i", "mentioned"], ["who", "i", "am"],
  ["have", "i"], ["i", "asked"], ["you", "said"], ["you", "told"], ["you", "mentioned"],
  ["we", "discussed"], ["we", "talked"], ["this", "call"], ["did", "you"], ["did", "we"],
  ["repeat", "the"], ["repeat", "what"], ["repeat", "your"], ["last", "answer"], ["last", "question"],
  ["first", "question"], ["say", "it", "again"],
  // agreeing to what the agent offered
  ["sounds", "good"], ["sounds", "great"], ["sounds", "fine"], ["let", "s", "do"], ["let", "s", "go"],
  ["lock", "it"], ["go", "ahead"], ["works", "for"],
  // personalised advice or prices
  ["should", "i", "order"], ["should", "i", "buy"], ["should", "i", "get"], ["should", "i", "choose"],
  ["should", "i", "pick"], ["best", "for", "me"], ["good", "for", "me"], ["right", "for", "me"],
  ["suitable", "for", "me"], ["recommend", "for", "me"], ["recommend", "me"], ["will", "i", "pay"],
  ["would", "i", "pay"], ["do", "i", "owe"],
  // live data
  ["in", "stock"], ["out", "of", "stock"], ["right", "now"], ["at", "the", "moment"], ["still", "on"],
  ["open", "now"], ["available", "now"], ["working", "now"], ["down", "now"],
  ["app", "down"], ["site", "down"], ["website", "down"], ["server", "down"], ["system", "down"],
  ["app", "working"], ["site", "working"], ["website", "working"], ["the", "wait"], ["wait", "time"],
  // dialogue
  ["i", "meant"], ["say", "that", "again"], ["repeat", "that"], ["come", "again"], ["slow", "down"],
  ["speak", "in"], ["talk", "in"], ["in", "hindi"], ["in", "english"], ["third", "time"],
  ["nobody", "is", "helping"], ["no", "one", "is", "helping"], ["not", "helping"], ["fed", "up"],
  // steering
  ["from", "now", "on"], ["act", "as"], ["you", "are", "now"], ["role", "play"], ["always", "say"],
  ["forget", "everything"], ["forget", "what"], ["forget", "your"], ["forget", "all"],
  ["for", "the", "rest"], ["tell", "everyone"], ["your", "rules"],
  ["your", "instructions"], ["previous", "instructions"], ["system", "prompt"],
  // sensitive advice
  ["safe", "during"], ["safe", "for", "kids"],
  ...CRISIS_PHRASES,
  ["sounds", "right"], ["uh", "huh"], ["that", "s", "it"],
  // Indian-English and Hinglish introductions, personal fit, hand-over, steering
  ["this", "side"], ["bol", "raha"], ["bol", "rahi"], ["name", "you", "have"], ["have", "for", "me"], ["suit", "me"], ["suits", "me"], ["me", "best"], ["put", "me", "through"], ["transfer", "me"], ["connect", "me"], ["from", "here", "on"], ["call", "yourself"],
];
const NEVER_PHRASES_BY_FIRST = firstWords(NEVER_PHRASES);
// Things the caller did or went through. With a how-to after them the turn may be
// answered from the cache, but what they said is never stored.
const STORY_PHRASES = [
  ["i", "ordered"], ["i", "bought"], ["i", "paid"], ["i", "placed"], ["i", "received"],
  ["i", "purchased"], ["i", "returned"], ["i", "booked"], ["i", "cancelled"], ["i", "canceled"],
  ["i", "was", "charged"], ["i", "got", "charged"], ["i", "haven", "t"], ["i", "didn", "t"],
  ["charged", "twice"], ["double", "charged"], ["i", "can", "t"], ["we", "can", "t"],
  ["i", "cannot"], ["we", "cannot"], ["i", "couldn", "t"], ["i", "am", "not", "able"],
  ["i", "m", "not", "able"],
];
const STORY_PHRASES_BY_FIRST = firstWords(STORY_PHRASES);
const PAST_TENSE = new Set([
  "lost", "got", "had", "was", "were", "broke", "fell", "left", "went", "came", "took",
  "made", "saw", "gave", "found", "sent", "paid", "bought", "forgot", "spent", "became",
  "hurt", "felt", "heard", "met", "ran", "told", "sold", "wrote", "drove", "flew", "won",
  "lent", "stole", "ate", "drank", "kept", "slept", "woke", "been",
]);
// Past forms that ask rather than tell: "i wanted to know", "i was wondering".
const NOT_A_STORY = new Set(["wanted", "wondered", "hoped", "needed", "liked", "loved", "wished", "preferred"]);
const STORY_FILLERS = new Set(["just", "recently", "already", "also", "never", "have", "ve"]);
const DIGITS = /[0-9]{5,}/;
// Digits read out in groups: "4 4 0 9", "98 765 43". Commas and points are left
// out, so a price ("1,499") or a weight ("1.5") is not an identifier.
const SPACED_DIGITS = /[0-9]+(?:[ \t-]+[0-9]+)+/g;
const EMAIL = /[A-Za-z0-9._%+-]@[A-Za-z0-9-]/;
const CLAUSES = /([,.!?;:]+)/;
const LETTER = /\p{L}/u;

// A turn longer than this is private without being read: every rule is linear in
// its length, and a caller's monologue is not a question other callers ask.
const MAX_TURN_CHARS = 1000;

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
const DISCLOSURE_LEADS = [
  ["i", "m"], ["i", "am"], ["i", "have"], ["i", "ve"], ["i", "took"], ["i", "take"], ["i", "was"],
  ["i", "had"], ["i", "got"], ["i", "owe"], ["like", "me"], ["for", "me"],
];
const DISCLOSURE_LEADS_BY_FIRST = firstWords(DISCLOSURE_LEADS);
// A state of the caller's own that changes the answer ("im pregnant, can i fly", "i want
// to invest my savings, how do i start"): with ANY first-person word, private whatever
// the framing, and so is a turn that opens with one ("pregnant at 30 weeks, can i fly").
// Professions ("what should i do if a doctor is late") and words with an everyday sense
// ("can i book a tennis court") are left to the disclosure rule.
const STATES = new Set([...MATTERS, "invest", "investment", "investing"]);
for (const word of [
  "doctor", "doctors", "lawyer", "lawyers", "attorney", "legal", "police", "court", "hospital",
  "therapist", "psychiatrist", "hit", "hits", "hitting", "beat", "beats", "beating", "passed",
  "afford",
]) STATES.delete(word);
const SELF_MARKERS = new Set(["i", "im", "iam", "ive", "me", "my", "mine", "myself", "mi", "mai", "we", "us", "our", "ours"]);
// "Pregnant women, is coffee safe?" asks about a kind of person, not the caller.
const KINDS_OF_PEOPLE = new Set([
  "women", "woman", "people", "person", "persons", "mothers", "mums", "moms", "ladies",
  "patients", "travellers", "travelers", "passengers", "customers", "guests", "kids",
  "children", "folks",
]);
// Other people the caller speaks for: "for my wife", "my son was arrested".
const RELATIONS = new Set([
  "husband", "wife", "partner", "son", "daughter", "child", "children", "kid", "kids", "baby",
  "mother", "mom", "mum", "father", "dad", "brother", "sister", "parent", "parents",
  "boyfriend", "girlfriend", "fiance", "fiancee", "grandmother", "grandfather", "grandma",
  "grandpa", "uncle", "aunt", "nephew", "niece", "cousin", "family", "friend", "neighbour",
  "neighbor", "bhai", "didi", "behen",
]);
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
const DATE = /(?<![0-9])[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}(?![0-9])/;
const STREET_WORDS = new Set([
  "street", "st", "road", "rd", "lane", "ln", "avenue", "ave", "drive", "boulevard", "blvd",
  "marg", "nagar", "colony", "sector", "apartments", "tower", "towers", "block", "society",
  "crescent", "terrace", "court", "place", "square", "highway", "calle", "rua", "rue",
  "avenida", "strasse", "straße", "plaza", "platz",
]);
// Codes and numbers that identify on their own: "#7741", "AB-7741", "b-204", "AI302",
// "is 4409 right" (not a year, a price, or an amount of something).
const HASH_NUMBER = /#\s*[0-9]{3,}/;
const CODE = /(?<![A-Za-z0-9])[A-Za-z]{1,4}-?[0-9]{3,}(?![A-Za-z0-9])/;
const QUANTITIES =
  "rupees|rs|inr|dollars|usd|euros|eur|pounds|gbp|units|items|pieces|people|guests|users|mb|gb|tb|kb|" +
  "mah|km|kg|g|ml|calories|steps|words|pages|points|miles|sq|square|feet|ft|sqft|watts|w|rpm|hours|" +
  "minutes|seconds|days|years|plan|model|series|edition|k|mp";
const BARE_NUMBER = new RegExp(
  "(?<![0-9.,$€£₹])(?<![$€£₹]\\s)(?!(?:19|20)[0-9]{2}(?![0-9]))[0-9]{4,}(?![0-9.,])" +
    "(?!\\s*(?:" + QUANTITIES + ")\\b)",
  "i"
);
const ENDS_IN = [["ends", "in"], ["ends", "with"], ["ending", "in"], ["ending", "with"], ["end", "in"]];
const UNIT_WORDS = new Set(["flat", "apartment", "apt", "house", "unit", "plot", "suite", "door", "sector", "block"]);
const DECIMAL = /\p{Nd}/gu;
const HAS_DECIMAL = /\p{Nd}/u;
const ALNUM = /^[\p{L}\p{N}]$/u;

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

const isStreetWord = (w) => STREET_WORDS.has(w);
const isNumberNear = (n) => hasDigit(n) || NUMBER_WORDS.has(n) || ORDINALS.has(n);
const isNumberWord = (n) => hasDigit(n) || NUMBER_WORDS.has(n);

// A number, date, email, spelling or address that can identify someone.
function identifies(text, words) {
  const ids = words.some((w) => ID_WORDS.has(w));
  // "is 4409 the right pin", "where is order 742"
  if (ids && words.some((w) => hasDigit(w) && [...w].length >= 3)) return true;
  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    // "i'm 45", "i owe 40000", "my pin is 4409"
    const reach = word === "i" || word === "we" ? 2 : POSSESSIVES.has(word) ? 3 : 0;
    if (reach && anyIn(words, index + 1, index + 1 + reach, amount)) return true;
    // "42 park lane", "flat 12"
    if (hasDigit(word) && anyIn(words, index + 1, index + 5, isStreetWord)) return true;
    if (UNIT_WORDS.has(word) && anyIn(words, index + 1, index + 3, hasDigit)) return true;
    // "priya sharma at gmail", "send it to priya at hotmail"
    if (word === "at" && index + 1 < words.length && words[index + 1].endsWith("mail")) return true;
  }
  if (HASH_NUMBER.test(text) || CODE.test(text) || BARE_NUMBER.test(text)) return true;
  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    // "card number ends with four four", "ends in 09"
    if (ENDS_IN.some((p) => startsWith(words, index, p)) && anyIn(words, index + 2, index + 4, isNumberWord)) return true;
    // "house number twelve", "calle mayor 10"
    if (UNIT_WORDS.has(word) && anyIn(words, index + 1, index + 4, (w) => NUMBER_WORDS.has(w))) return true;
    if (STREET_WORDS.has(word) && anyIn(words, index + 1, index + 4, hasDigit)) return true;
  }
  const tied = ids || words.some((w) => FIRST_PERSON.has(w));
  if (tied && DATE.test(text)) return true;
  if (tied && words.some((w, i) => MONTHS.has(w) && anyIn(words, i - 2, i + 3, isNumberNear))) return true;
  if (words.includes("at") && (words.includes("email") || words.includes("mail"))) return true;
  // Letters spelled out: "j o h n", "x j 4 k q".
  let run = 0;
  for (const raw of text.split(/\s+/).filter(Boolean)) {
    const token = raw.replace(TRIM_EDGES, "");
    run = [...token].length === 1 && ALNUM.test(token) ? run + 1 : 0;
    if (run >= 3) return true;
  }
  return false;
}

// Words that start a name when said alone in a clause: "i'm priya", "soy carlos".
const INTRO_LEADS = [
  ["i", "am"], ["i", "m"], ["this", "is"], ["it", "s"], ["it", "is"], ["soy"], ["je", "suis"],
  ["ich", "bin"], ["eu", "sou"], ["sono"], ["ik", "ben"], ["aqui", "é"], ["aqui", "e"], ["sou"],
  ["habla"], ["fala"], ["ici"],
];
// Phrases a name always follows, in the languages callers use.
const INTRODUCTIONS = [
  ["mi", "nombre"], ["me", "llamo"], ["je", "m", "appelle"], ["mon", "nom"], ["mein", "name"],
  ["ich", "heisse"], ["ich", "heiße"], ["meu", "nome"], ["me", "chamo"], ["mi", "chiamo"],
  ["mijn", "naam"], ["mera", "naam"], ["meri", "naam"], ["naam", "hai"], ["myname"],
  ["you", "re", "speaking", "with"], ["you", "are", "speaking", "with"], ["you", "re", "talking", "to"],
  ["you", "are", "talking", "to"], ["ke", "naam"], ["ka", "naam"], ["ki", "naam"], ["naam", "pe"],
  ["naam", "par"], ["naam", "se"],
];
const INTRODUCTIONS_BY_FIRST = firstWords(INTRODUCTIONS);
const NAME_ARTICLES = new Set(["o", "a", "el", "la", "le"]);
const CLAUSE_OPENERS = new Set([
  ...DISCOURSE, ...GREETINGS, "hola", "bonjour", "salut", "hallo", "ola", "olá", "ciao", "um", "uh", "well",
]);
// Before a capitalised word, these make it a person: "for Rahul", "Dr Mehta",
// "does Mohit have".
const NAME_SLOTS = new Set(["for", "dr", "prof", "sir", "madam", "miss", "shri", "smt"]);
const TITLES = new Set([...NAME_SLOTS].filter((w) => w !== "for"));
const AUXILIARIES = new Set(["can", "could", "does", "did", "is", "has", "had", "will", "would", "should", "may", "was"]);
// What a person, not a product, does after an opening auxiliary: "does Mohit have".
const PERSON_VERBS = new Set([
  "have", "has", "had", "need", "want", "pick", "get", "come", "coming", "call", "called",
  "know", "live", "book", "booked", "order", "ordered", "pay", "paid", "arrive", "arrived",
  "still", "already", "sign", "signed", "speak", "talk", "collect", "collects", "visit", "attend",
]);
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
// "Can I speak to Meera", "pls connect to raghav sir": a person asked for by name.
const ASK_FOR = [
  ["speak", "to"], ["speak", "with"], ["talk", "to"], ["talk", "with"], ["connect", "to"],
  ["connect", "me", "to"], ["transfer", "to"], ["transfer", "me", "to"], ["ask", "for"],
  ["put", "me", "through", "to"],
];
const ASK_FOR_BY_FIRST = firstWords(ASK_FOR);
const ROLES = new Set([
  "someone", "somebody", "anyone", "anybody", "agent", "human", "person", "manager",
  "representative", "operator", "sales", "billing", "accounts", "department", "reception",
  "front", "staff", "engineer", "technician", "executive", "advisor", "adviser", "officer",
]);
const POSSESSIVE_NAME = /(\p{L}+)['’]s\s+(\p{L}+)/gu;
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

function namesSomeone(text, words) {
  if (hasPhrase(words, INTRODUCTIONS_BY_FIRST)) return true;
  const personal = words.some((w) => PERSONAL_MATTERS.has(w) || PERSON_CUES.has(w));
  for (let index = 0; index < words.length; index += 1) {
    for (const phrase of ASK_FOR_BY_FIRST.get(words[index]) || []) {
      const end = index + phrase.length;
      if (startsWith(words, index, phrase) && end < words.length && unknown(words[end])) return true;
    }
  }
  // "is sanjay's order ready", in any case
  for (const match of text.matchAll(POSSESSIVE_NAME)) {
    if (unknown(match[1].toLowerCase()) && PERSONAL_MATTERS.has(match[2].toLowerCase())) return true;
  }
  // "rahul ka order", "priya ki booking"
  for (let index = 1; index + 1 < words.length; index += 1) {
    if (
      ["ka", "ki", "ke"].includes(words[index]) && PERSONAL_MATTERS.has(words[index + 1]) &&
      unknown(words[index - 1]) && !FUNCTION_WORDS.has(words[index - 1])
    ) {
      return true;
    }
  }
  const parts = text.split(CLAUSES);
  for (let index = 0; index < parts.length; index += 2) {
    let said = wordsOf(parts[index]);
    while (said.length && CLAUSE_OPENERS.has(said[0])) said = said.slice(1);
    // "priya here", "priya speaking"
    if (
      said.length >= 2 && said.length <= 3 && (said[said.length - 1] === "here" || said[said.length - 1] === "speaking") &&
      !(WH_WORDS.has(said[0]) || QUESTION_LEADS.has(said[0]) || FUNCTION_WORDS.has(said[0]))
    ) {
      return true;
    }
    for (const lead of INTRO_LEADS) {
      let rest = said.slice(lead.length);
      while (!["i", "this", "it"].includes(lead[0]) && rest.length && NAME_ARTICLES.has(rest[0])) rest = rest.slice(1); // "sou a mariana"
      if (!startsWith(said, 0, lead) || !rest.length) continue;
      if (rest.length <= 3 && !rest.some((w) => FUNCTION_WORDS.has(w) || WH_WORDS.has(w))) return true;
      if (unknown(rest[0]) && !FUNCTION_WORDS.has(rest[0])) return true; // "i'm vikram and i want ..."
    }
    // "can priya pick up the order", "will priya get the refund", in any case
    if (said.length > 2 && AUXILIARIES.has(said[0]) && unknown(said[1]) && PERSON_VERBS.has(said[2]) && personal) {
      return true;
    }
  }
  return capitalisedName(text, words);
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

// The caller's own health, legal, abuse or money matter, told in the first person,
// or someone's they speak about.
function discloses(words) {
  return words.some((w) => MATTERS.has(w)) && (
    words.some((w) => POSSESSIVES.has(w) || SOMEONE.has(w)) ||
    hasPhrase(words, DISCLOSURE_LEADS_BY_FIRST)
  );
}

// Something of the caller's in a story: who else, a number, a name, a matter. The
// caller's own things ("i forgot my password") stay as general as "how do i reset my password".
function carriesDetail(text, words) {
  return (
    words.some((w) => MATTERS.has(w) || RELATIONS.has(w) || THIRD_PERSON.has(w)) ||
    words.some(hasDigit) ||
    properNouns(text).size > 0
  );
}

function tooLong(text) {
  let count = 0;
  for (const _ of text) {
    count += 1;
    if (count > MAX_TURN_CHARS) return true;
  }
  return false;
}

function startsWith(words, at, phrase) {
  return phrase.every((w, k) => words[at + k] === w);
}

// Letters these rules cannot read: anything outside the Latin script. A turn
// the rules cannot read cannot be shown to be safe to share.
function unreadable(text) {
  for (const ch of text) {
    if (!LETTER.test(ch)) continue;
    const latin = (ch >= "a" && ch <= "z") || (ch >= "A" && ch <= "Z") ||
      (ch >= "À" && ch <= "ɏ") || (ch >= "Ḁ" && ch <= "ỿ");
    if (!latin) return true;
  }
  return false;
}

function readsOutDigits(text, words) {
  for (const group of text.match(SPACED_DIGITS) || []) {
    if ((group.match(/[0-9]/g) || []).length >= 4) return true;
  }
  let run = 0;
  for (const word of words) {
    // "seven four two", "forty four oh nine", "double four zero nine"
    const spoken = NUMBER_WORDS.has(word) || /^[0-9]$/.test(word);
    run = spoken ? run + 1 : 0;
    if (run >= 3) return true;
  }
  return false;
}

// A clause that opens with a verb acting on something: "set a timer", "fine, book it".
function commands(text) {
  const parts = text.split(CLAUSES);
  for (let index = 0; index < parts.length; index += 2) {
    if ((parts[index + 1] || "").includes("?")) continue;
    let words = wordsOf(parts[index]);
    while (words.length && DISCOURSE.has(words[0])) words = words.slice(1);
    if (
      words.length > 1 && ACTION_VERBS.has(words[0]) && ACTION_OBJECTS.has(words[1]) &&
      !words.some((w) => WH_WORDS.has(w))
    ) {
      return true;
    }
  }
  return false;
}

function asserts(text, words) {
  let rest = words.filter((w) => !GREETINGS.has(w));
  while (rest.length && (SOFT_REPLY_LEADS.has(rest[0]) || CONNECTIVES.has(rest[0]))) rest = rest.slice(1);
  return (
    rest.length > 0 && STATEMENT_SUBJECTS.has(rest[0]) && !text.includes("?") &&
    !rest.some((w) => WH_WORDS.has(w)) && rest.some((w) => STATEMENT_VERBS.has(w))
  );
}

function tellsOwnStory(words) {
  if (hasPhrase(words, STORY_PHRASES_BY_FIRST)) return true;
  for (let index = 0; index + 1 < words.length; index += 1) {
    if (words[index] !== "i" && words[index] !== "we") continue;
    let at = index + 1;
    while (at < words.length - 1 && STORY_FILLERS.has(words[at])) at += 1;
    const verb = words[at];
    const after = at + 1 < words.length ? words[at + 1] : "";
    if ((verb === "was" || verb === "were") && after.endsWith("ing")) continue;
    const regular = verb.endsWith("ed") && !verb.endsWith("eed"); // "ordered", not "need"
    if (PAST_TENSE.has(verb) || (verb.length > 3 && regular && !NOT_A_STORY.has(verb))) return true;
  }
  return false;
}

// Whether a turn's answer must never be shared, whatever the rest of the rules say.
function neverShare(text, words) {
  if (unreadable(text)) return true;
  if (DIGITS.test(text) || EMAIL.test(text) || readsOutDigits(text, words)) return true;
  if (words.includes("at") && words.includes("dot") && words.some((w) => EMAIL_ENDINGS.has(w))) return true;
  if (words.some((w) => SINGLE_WORDS.has(w)) || hasPhrase(words, NEVER_PHRASES_BY_FIRST)) return true;
  if (identifies(text, words) || namesSomeone(text, words)) return true;
  if (words.length && GREETINGS.has(words[0])) {
    const rest = words.filter((w) => !GREETINGS.has(w));
    if (INTRO_AFTER_GREETING.some((p) => startsWith(rest, 0, p))) return true;
  }
  if (words.length > 1 && words.length <= 5 && (words[words.length - 1] === "here" || words[words.length - 1] === "speaking")) {
    return true;
  }
  if (words.length && words[0] === "myself") return true; // "Myself Anjali, I need help."
  for (let index = 0; index < words.length; index += 1) {
    if (!POSSESSIVES.has(words[index])) continue;
    for (const at of [index + 1, index + 2]) {
      // "my phone", "my washing machine"
      if (at < words.length && OWNED_THINGS.has(words[at]) && words.slice(at + 1, at + 5).some((w) => STATE_WORDS.has(w))) {
        return true;
      }
    }
  }
  if (commands(text)) return true;
  for (let index = 0; index < words.length; index += 1) {
    for (const lead of ACTION_LEADS_BY_FIRST.get(words[index]) || []) {
      const end = index + lead.length;
      if (startsWith(words, index, lead) && end < words.length && ACTION_VERBS.has(words[end])) return true;
    }
  }
  if (words.length && !words.some((w) => WH_WORDS.has(w))) {
    if (REPLY_LEADS.has(words[0])) return true;
    if (SOFT_REPLY_LEADS.has(words[0])) {
      let rest = words.slice(1);
      while (rest.length && (SOFT_REPLY_LEADS.has(rest[0]) || CONNECTIVES.has(rest[0]))) rest = rest.slice(1);
      if (!rest.length || !QUESTION_LEADS.has(rest[0])) return true;
    }
  }
  if (asserts(text, words)) return true;
  for (let index = 0; index + 2 < words.length; index += 1) {
    // "how many points do i have", not "do i have to pay for returns"
    if (startsWith(words, index, ["do", "i", "have"]) && (index + 3 >= words.length || words[index + 3] !== "to")) {
      return true;
    }
  }
  return false;
}

// "i have lupus", "tengo lupus", "j'ai la sclérose", "i was diagnosed with ...": the
// shape of a diagnosis, so the condition need not be in any list.
const DIAGNOSIS_LEADS = [
  ["i", "have"], ["i", "ve", "got"], ["i", "got"], ["tengo"], ["tenho"], ["j", "ai"],
  ["diagnosed"], ["suffering", "from"], ["suffer", "from"], ["sufro", "de"], ["sofro", "de"],
  ["souffre", "de"], ["padezco"], ["mujhko"],
];
const DIAGNOSIS_LEADS_BY_FIRST = firstWords(DIAGNOSIS_LEADS);
const ARTICLES = new Set(["a", "an", "un", "una", "uma", "um", "une", "la", "le", "el", "de", "with"]);
// What a caller "has" that is not a condition: "i have a question", "tengo una duda".
const HAVE_OBJECTS = new Set([
  "question", "questions", "query", "queries", "doubt", "doubts", "issue", "issues", "problem",
  "problems", "concern", "concerns", "complaint", "feedback", "suggestion", "idea", "time",
  "money", "cash", "access", "permission", "enough", "nothing", "something", "everything",
  "some", "already", "just", "also", "still", "been", "got", "pregunta", "preguntas", "duda",
  "dudas", "problema", "pergunta", "perguntas", "dúvida", "duvida", "minute", "moment", "second",
  "another", "more", "few", "several", "multiple",
]);

function diagnosis(words) {
  for (let index = 0; index < words.length; index += 1) {
    for (const lead of DIAGNOSIS_LEADS_BY_FIRST.get(words[index]) || []) {
      if (!startsWith(words, index, lead)) continue;
      let end = index + lead.length;
      while (end < words.length && ARTICLES.has(words[end])) end += 1;
      if (end < words.length && unknown(words[end]) && !HAVE_OBJECTS.has(words[end]) && !hasDigit(words[end])) return true;
    }
  }
  return false;
}

// A sensitive state with any first-person word, or a turn that opens with one.
function sensitiveSelf(words) {
  if (words.length && STATES.has(words[0]) && (words.length === 1 || !KINDS_OF_PEOPLE.has(words[1]))) return true;
  return words.some((w) => STATES.has(w)) && words.some((w) => SELF_MARKERS.has(w));
}

const ASKING_WORDS = new Set([...WH_WORDS, "kya", "kab", "kahan", "kaise", "kitna", "kitne", "kaun", "kyun", "kyon"]);
const ASKING_LEADS = new Set([...QUESTION_LEADS, ...CLAUSE_MARKERS, ...ACTION_VERBS]);

const FIRST_CLAUSE = /[,.\-–—]/;
// Clauses that say nothing either way: "hi", "okay", "thanks".
const NEUTRAL = new Set([...CLAUSE_OPENERS, ...SOFT_REPLY_LEADS, ...REPLY_LEADS, "thanks", "thank", "you"]);

// Shaped as a question or a request from its first clause on: "Bipolar, can you
// help?" is not, "Hi, what are your hours?" is. A greeting or acknowledgement first is
// skipped.
function asks(text) {
  for (const clause of String(text).split(FIRST_CLAUSE)) {
    const said = wordsOf(clause);
    if (!said.length || said.every((w) => NEUTRAL.has(w))) continue;
    return (
      clause.includes("?") || said.some((w) => ASKING_WORDS.has(w)) || ASKING_LEADS.has(said[0]) ||
      hasPhrase(said, ACTION_LEADS_BY_FIRST) || procedural(said)
    );
  }
  return false;
}

function isPersonal(text) {
  const source = String(text === null || text === undefined ? "" : text);
  if (tooLong(source)) return true;
  const words = wordsOf(source);
  if (
    neverShare(source, words) || describesCaller(words) || discloses(words) || sensitiveSelf(words) ||
    urgent(words) || diagnosis(words)
  ) {
    return true;
  }
  const owned = ownedRecordAt(words);
  const story = tellsOwnStory(words);
  const advice = words.some((w) => SENSITIVE.has(w)) && words.some((w) => FIRST_PERSON.has(w));
  if (owned < 0 && !story && !advice) return false;
  // A how-to after the caller's story may be looked up, unless the story holds
  // something of theirs: then nothing of it leaves the SDK.
  if (procedural(words)) return story && carriesDetail(source, words);
  if (story || advice || requests(words)) return true;
  if (owned > 0 && OWNER_PREPOSITIONS.has(words[owned - 1])) {
    // "i'm calling for my mother": someone else the caller speaks for
    return RELATIONS.has(words[owned + 1]) || isStateInterrogative(words);
  }
  return true;
}

// A how-to after the caller's own story ("i received a damaged product, how do i
// return it"): a shared answer may be served, but nothing of the turn is stored.
function lookupOnly(text) {
  return !isPersonal(text) && tellsOwnStory(wordsOf(text));
}

function hasAntecedent(before) {
  return before.some((word) => !FUNCTION_WORDS.has(word) && !NON_REFERENTS.has(word));
}

// An "it" whose subject comes after it: "what does it cost to send a parcel",
// "is it true that ...". "Is it refundable to the card" still points back.
function pointsForward(words, index) {
  const ahead = words.slice(index + 1, index + 4);
  for (let offset = 0; offset < ahead.length; offset += 1) {
    if (["that", "if", "whether"].includes(ahead[offset])) return true;
    if (ahead[offset] === "to") {
      const after = index + 2 + offset;
      return after < words.length && !FUNCTION_WORDS.has(words[after]);
    }
  }
  return false;
}

function hasBareAnaphor(words) {
  const joined = words.join(" ");
  for (const phrase of ANAPHOR_PHRASES) {
    const at = joined.indexOf(phrase);
    if (at >= 0 && !hasAntecedent(splitPlain(joined.slice(0, at)))) return true;
  }
  for (let index = 0; index < words.length; index += 1) {
    const word = words[index];
    if (!ANAPHORS.has(word)) continue;
    const follows = index + 1 < words.length ? words[index + 1] : null;
    if (
      DEMONSTRATIVES.has(word) &&
      follows !== null &&
      !FUNCTION_WORDS.has(follows) &&
      !PRONOUN_FOLLOWERS.has(follows)
    ) {
      continue;
    }
    if (word === "it" && pointsForward(words, index)) continue;
    if (!hasAntecedent(words.slice(0, index))) return true;
  }
  return false;
}

function isContextDependent(text) {
  if (tooLong(String(text === null || text === undefined ? "" : text))) return false; // private anyway, and keyed on its own
  const words = wordsOf(text);
  if (!words.length) return false;
  if (CONNECTIVES.has(words[0])) return true;
  if (CONNECTIVE_PAIRS.has(words.slice(0, 2).join(" "))) return true;
  if (ELLIPSIS_LEADS.has(words[0]) && !words.slice(1).some((w) => CLAUSE_MARKERS.has(w))) {
    return true;
  }
  if (hasPhrase(words, FOLLOW_UP_PHRASES_BY_FIRST) || FOLLOW_UP_ENDINGS.has(words[words.length - 1])) {
    return true;
  }
  if (words.every((w) => FUNCTION_WORDS.has(w) || NON_REFERENTS.has(w) || BARE.has(w))) return true;
  return hasBareAnaphor(words);
}

function slotNames(shape) {
  return [...String(shape).matchAll(SLOT)].map((found) => found[1]);
}

// One pass: a value that itself contains "{other}" is spoken as-is, never
// expanded into another slot's value.
function fill(shape, values) {
  for (const name of slotNames(shape)) {
    if (values[name] === undefined || values[name] === null) return null;
  }
  return String(shape).replace(SLOT, (_, name) => values[name]);
}

// Replaced only as whole words, and one- or two-character values not at all:
// count=2 must not turn "24 hours" into "{count}4 hours".
const MIN_ABSTRACT_LEN = 3;

function escapeRegExp(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function abstract(answer, values) {
  let shaped = String(answer);
  const pairs = Object.entries(values).sort(
    (left, right) => String(right[1] || "").length - String(left[1] || "").length
  );
  for (const [name, value] of pairs) {
    if (value && value.length >= MIN_ABSTRACT_LEN) {
      const pattern = new RegExp(`(?<![\\p{L}\\p{N}_])${escapeRegExp(value)}(?![\\p{L}\\p{N}_])`, "gu");
      shaped = shaped.replace(pattern, `{${name}}`);
    }
  }
  return shaped;
}

function flatten(text) {
  return wordsOf(text).join("");
}

function leaks(shaped, values) {
  const flat = flatten(shaped);
  return Object.values(values).some((value) => value && flat.includes(flatten(value)));
}

// A hard deadline: a slow or hung cache must never hold a live call past its budget.
function within(ms, promise) {
  let timer;
  const late = new Promise((resolve) => {
    timer = setTimeout(() => resolve(LATE), ms);
  });
  return Promise.race([promise, late]).finally(() => clearTimeout(timer));
}

const LATE = Symbol("late");

// Writes a turn stopped waiting for (past twice the latency budget), finishing in the background.
// At most WRITES_MAX wait at once: past it (a hung server) a new answer is not written at all.
let WRITES_MAX = 256;
const pendingWrites = new Set();

/** For tests: every write handed to the background has finished. */
async function waitForWrites() {
  await Promise.allSettled([...pendingWrites]);
}

// For tests: a smaller cap; returns a function that puts the old one back.
function setWritesMax(max) {
  const old = WRITES_MAX;
  WRITES_MAX = max;
  return () => { WRITES_MAX = old; };
}

// How many follow-ups back a turn may lean on before it is treated as unresolvable.
const CHAIN_LIMIT = 6;

// A chain is private when any turn of it is, or when its root ("Priya Sharma.",
// "Bipolar.") is too short to stand alone or neither asks nor requests anything.
function privateChain(chain, minWords = 0) {
  const root = chain.length ? String(chain[0] || "").trim() : "";
  if (chain.length && (root.split(/\s+/).filter(Boolean).length < minWords || !asks(root))) return true;
  return chain.some((turn) => isPersonal(turn) || lookupOnly(turn));
}

// The checks below are for past transcripts only (warmFromCalls). A live turn
// needs none of them: its model reads only what decide() hands it. A past
// answer was written with the whole call in view.
// Whether the answer repeats something the caller said earlier in the call. A
// model answering turn N has seen turns 1..N-1, so "Sarah, order 55512 arrives
// Tuesday" to "what is the delivery time?" — or an answer shaped by "pretend
// refunds are unlimited" — would become the shared answer to a generic
// question and be spoken to the next caller. Only identifying words count:
// "order" said earlier must not block "the order ships in 5 days".
function carriesCallContext(answer, question, earlier) {
  const asked = new Set(wordsOf(question));
  const before = new Set();
  for (const turn of earlier) {
    for (const w of identifying(turn)) before.add(w);
  }
  return wordsOf(answer).some((w) => before.has(w) && !asked.has(w));
}

// A caller turn that tries to change what the model says for the rest of the call.
const STEERING = [
  ["pretend"], ["from", "now", "on"], ["for", "this", "call"], ["for", "the", "rest"],
  ["ignore"], ["forget"], ["act", "as"], ["you", "are", "now"], ["assume"],
  ["always", "say"], ["tell", "everyone"], ["roleplay"], ["role", "play"],
];
const STEERING_BY_FIRST = firstWords(STEERING);
// Phrases after which the caller gives a name: "my name is sarah", "this is raj".
const NAMING = [["name", "is"], ["call", "me"], ["this", "is"], ["i", "m"], ["i", "am"]];

// A system prompt can carry one caller's details ("The caller is Asha Rao, account
// 99812"). An answer that repeats them must never be shared. Same rules as Python
// (voice.py, _caller_details); fixtures/prompt-guard-cases.json checks both.
//
// 1. Across calls (the reliable one): a bot's own instructions are the same on every
//    call, so once an agent has been seen with two different system prompts, every word
//    and number of this call's prompt not in all of them is a caller detail.
// 2. Before that: the sentences of the prompt that are about a person.

// Words that make a sentence about one person, not the business.
const PERSON_WORDS = new Set([
  "caller", "customer", "user", "client", "patient", "member", "guest", "student",
  "name", "named", "account", "acct", "dob", "birthday", "born", "called", "calling",
  "talking", "speaking", "mr", "mrs", "ms", "mx", "miss", "dr", "prof", "he", "she", "him",
  "his", "her", "hers",
]);
// A "label: value" line about one person's record or contact ("Phone: 555 0199",
// "Location: Pune"), unless the label says it is the business's own.
const RECORD_LABELS = new Set([
  "phone", "mobile", "email", "address", "order", "booking", "reservation", "ticket", "case",
  "policy", "plan", "balance", "dob", "id", "city", "location", "company", "employer",
]);
// Words that make a sentence about the business even when it names a person word.
const BUSINESS_WORDS = new Set([
  "support", "our", "office", "helpline", "help", "toll", "free", "business", "sales",
  "main", "head", "store", "shop", "branch", "service", "services", "care", "line", "we",
  "us", "customers", "callers", "users", "clients", "patients", "members", "guests",
]);
const LABEL_WORDS = new Set([...RECORD_LABELS, ...PERSON_WORDS]);
// Sentence ends: . ! ? or ; then space, or a line break; never the dots inside an email
// address or a decimal, nor the one after a title ("Mr. Sharma", "Prof. Rao").
const SENTENCE_END =
  /(?<!\bMr\.)(?<!\bMs\.)(?<!\bMx\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bSr\.)(?<!\bJr\.)(?<!\bMrs\.)(?<!\bProf\.)(?<=[.!?;])\s+/;
// Runs of digits that belong together ("555 0199", "1800-555-0100", "99,812") make one number.
const NUMBER_RUN = /[0-9]+(?:[ ,\-./][0-9]+)*/g;
const EMAIL_ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+/g;
const LABEL = /^\s*([^:=\n]{1,40}?)\s*[:=]\s*(.*)$/;

const isDecimalWord = (word) => /\p{Nd}/u.test(word);
const startsUpper = (word) => /^\p{Lu}/u.test(word);

function numbersOf(text) {
  return (String(text || "").match(NUMBER_RUN) || []).map((run) => run.replace(/[^0-9]/g, ""));
}

function labelOf(sentence) {
  const match = LABEL.exec(sentence);
  return match ? [match[1], match[2]] : ["", ""];
}

function aboutAPerson(sentence, words) {
  const present = new Set(words);
  if ([...present].some((w) => PERSON_WORDS.has(w)) && ![...present].some((w) => BUSINESS_WORDS.has(w))) return true;
  const [label, value] = labelOf(sentence);
  const labelWords = new Set(wordsOf(label));
  return Boolean(
    value.trim() && [...labelWords].some((w) => LABEL_WORDS.has(w)) && ![...labelWords].some((w) => BUSINESS_WORDS.has(w))
  );
}

function valueWords(value) {
  return wordsOf(value).filter(
    (w) => !FUNCTION_WORDS.has(w) && !LABEL_WORDS.has(w) && !isDecimalWord(w) && !EMAIL_ENDINGS.has(w)
  );
}

// Caller details in one system prompt, read on its own, as { words, numbers }: in its
// sentences about a person, the capitalised words (a sentence's first only when the next
// is capitalised too), email words, every number, and the whole value of a "Label: value"
// / "key=value" about a person's record. Lines under a heading about a person ("Caller
// record:"), up to a blank line, are all details.
function promptDetails(instructions) {
  const words = new Set();
  const numbers = new Set();
  let inBlock = false;
  for (const line of String(instructions || "").split("\n")) {
    if (!line.trim()) {
      inBlock = false;
      continue;
    }
    if (inBlock) {
      for (const w of valueWords(line)) words.add(w);
      for (const n of numbersOf(line)) if (n) numbers.add(n);
      continue;
    }
    for (const sentence of line.split(SENTENCE_END)) {
      const lowered = wordsOf(sentence);
      if (!lowered.length || !aboutAPerson(sentence, lowered)) continue;
      const [label, value] = labelOf(sentence);
      if (sentence.trimEnd().endsWith(":") && !value.trim()) inBlock = true;
      for (const n of numbersOf(sentence)) if (n) numbers.add(n);
      if (value.trim() && wordsOf(label).some((w) => LABEL_WORDS.has(w))) {
        for (const w of valueWords(value)) words.add(w);
      }
      const tokens = sentence.match(WORDS) || [];
      tokens.forEach((word, index) => {
        const low = word.toLowerCase();
        if (LABEL_WORDS.has(low) || FUNCTION_WORDS.has(low) || !startsUpper(word) || isDecimalWord(word)) return;
        if (index === 0 && !(index + 1 < tokens.length && startsUpper(tokens[index + 1]))) return;
        words.add(low);
      });
      for (const address of sentence.match(EMAIL_ADDRESS) || []) {
        for (const w of wordsOf(address)) if (!EMAIL_ENDINGS.has(w) && !/^\p{Nd}+$/u.test(w)) words.add(w);
      }
    }
  }
  return { words, numbers };
}

// What every system prompt an agent was seen with has in common, in this process.
const BASELINES = new Map();
const BASELINES_MAX = 1024;

function resetPromptBaselines() {
  BASELINES.clear();
}

// Caller details in this call's system prompt: what differs from the agent's other calls
// once its prompt has been seen to vary, the sentences about a person before that.
function callerDetails(instructions, agentKey = null) {
  if (agentKey === null || agentKey === undefined) return promptDetails(instructions);
  const words = new Set(wordsOf(instructions));
  const numbers = new Set(numbersOf(instructions).filter(Boolean));
  const key = JSON.stringify(agentKey);
  const baseline = BASELINES.get(key) || { prompts: new Set(), words: null, numbers: null };
  BASELINES.delete(key);
  BASELINES.set(key, baseline); // the most recent last; the oldest is dropped
  while (BASELINES.size > BASELINES_MAX) BASELINES.delete(BASELINES.keys().next().value);
  const text = String(instructions || "").trim();
  if (!baseline.prompts.has(text) && baseline.prompts.size < 2) baseline.prompts.add(text);
  baseline.words = baseline.words === null ? words : new Set([...baseline.words].filter((w) => words.has(w)));
  baseline.numbers = baseline.numbers === null ? numbers : new Set([...baseline.numbers].filter((n) => numbers.has(n)));
  // The sentences about a person always count: the first two prompts seen can both be one
  // caller's (only a date differs), so what is common to them is never taken as not a detail.
  const own = promptDetails(instructions);
  if (baseline.prompts.size < 2) return own;
  return {
    words: new Set([...[...words].filter((w) => !baseline.words.has(w) && !FUNCTION_WORDS.has(w)), ...own.words]),
    numbers: new Set([...[...numbers].filter((n) => !baseline.numbers.has(n)), ...own.numbers]),
  };
}

// One number, written with or without its country code or leading part: equal, or the
// longer ends with the shorter of at least 4 digits.
function sameNumber(said, detail) {
  if (said === detail) return true;
  const [short, long] = said.length <= detail.length ? [said, detail] : [detail, said];
  return short.length >= 4 && long.endsWith(short);
}

// Whether the answer repeats a detail the system prompt gave about this caller ("Hi
// Asha! We open at nine.", "account 99812") that the question itself did not contain.
// Such an answer was shaped by this caller's details and is never shared.
function repeatsPromptDetails(answer, question, instructions, agentKey = null) {
  const { words, numbers } = callerDetails(instructions, agentKey);
  if (!words.size && !numbers.size) return false;
  const askedWords = new Set(wordsOf(question));
  const askedNumbers = new Set(numbersOf(question));
  if (wordsOf(answer).some((w) => words.has(w) && !askedWords.has(w))) return true;
  return numbersOf(answer).some((n) => !askedNumbers.has(n) && [...numbers].some((d) => sameNumber(n, d)));
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

// What in a caller turn identifies the caller rather than the topic: numbers,
// names they gave, proper nouns — or, for a turn steering the model, every
// content word, since any of them can reshape the answer.
function identifying(turn) {
  const words = wordsOf(turn);
  if (hasPhrase(words, STEERING_BY_FIRST)) {
    return new Set(words.filter((w) => w.length >= 3 && !FUNCTION_WORDS.has(w)));
  }
  const found = new Set([...words.filter((w) => /\d/.test(w)), ...properNouns(turn)]);
  for (let index = 0; index < words.length; index += 1) {
    for (const phrase of NAMING) {
      const end = index + phrase.length;
      if (end < words.length && phrase.every((p, k) => words[index + k] === p) && !FUNCTION_WORDS.has(words[end])) {
        found.add(words[end]);
      }
    }
  }
  return found;
}

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
// How many already-checked caller turns a session remembers for _heard() (past it, a turn is checked again).
const HEARD_MAX = 2048;

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

// An answer that does not answer (a question back, "I'm not sure", a refusal) is
// spoken but never saved: cached, it becomes every later caller's answer, and it
// keeps rephrasings of the question from matching a real answer.
const NON_ANSWER_PHRASES = [
  "could you let me know", "could you tell me", "can you tell me", "could you clarify",
  "can you clarify", "could you specify", "can you specify", "could you provide",
  "can you provide", "please clarify", "please specify", "please provide", "let me know the ",
  "let me know which", "let me know what", "let me know your", "what do you mean",
  "which one do you mean", "i'm not sure", "i am not sure", "i don't know", "i do not know",
  "i can't help", "i cannot help", "i can't answer", "i cannot answer", "i'm unable to help",
  "i am unable to help", "i'm unable to answer", "i am unable to answer", "i'm unable to assist",
  "i am unable to assist", "i'm unable to find", "i am unable to find", "i don't have access", "i do not have access", "i don't have information",
  "i do not have information", "need more information", "need more details",
  "i need more information", "i need more details", "i'm not able to help", "i am not able to help",
  "i'm not able to answer", "i am not able to answer", "i'm not able to access", "i am not able to access",
  "i'm afraid i don't", "i'm afraid i can't", "i'm afraid i do not", "i'm afraid i cannot",
  "i'm not able to share", "i am not able to share", "i'm not able to provide", "i am not able to provide",
  "i can't provide", "i cannot provide", "i can't share", "i cannot share",
  "i can't determine", "i cannot determine", "i'm unable to determine", "i am unable to determine",
  "i'm not able to determine", "i am not able to determine", "i couldn't determine", "i could not determine",
  "it is impossible to determine", "it's impossible to determine", "it is not possible to determine",
  "it's not possible to determine",
];
// What follows "..., but" when a reply only points elsewhere: "but you can check a map".
const REDIRECTS = ["you ", "you'll", "you'd", "a quick search", "a search", "an online search", "i recommend", "i suggest", "i'd ", "i would ", "i can ", "please", "try", "check",
  "consider", "if you", "it's best", "it is best", "it would be best"];
// Openers that soften a non-answer without changing it: "Unfortunately I do not know".
const SOFTENERS = ["unfortunately ", "sadly ", "sorry ", "hmm ", "well ", "but "];
const SENTENCE = /[^.!?]+[.!?]*/g;

// Words a finished question rarely ends on: "do you deliver on" was cut off before its day.
const DANGLING = new Set(("on in at to for from with about of by into onto over under the a an and or but my your our their " +
  "his her its than if because like as between near via per until before after during within without " +
  "through since outside inside around across against any some whether").split(" "));
const TRAILING_FILLERS = new Set("um uh er erm uhm hmm mm".split(" "));
// "How do I log in?" is finished: the verb takes the word as its own.
const TAKES_IN_ON = new Set("log logged sign signed check checked opt opted".split(" "));

function unfinished(text) {
  const words = wordsOf(text);
  while (words.length && TRAILING_FILLERS.has(words[words.length - 1])) words.pop();
  const lastWord = words[words.length - 1];
  if (!lastWord || !DANGLING.has(lastWord)) return false;
  return !((lastWord === "in" || lastWord === "on") && words.length > 1 && TAKES_IN_ON.has(words[words.length - 2]));
}

function isNonAnswer(answer) {
  const text = String(answer || "").toLowerCase().replace(/’/g, "'").split(/\s+/).filter(Boolean).join(" ");
  const sentences = (text.match(SENTENCE) || []).map((s) => s.trim()).filter((s) => s.replace(/[ .!?]/g, ""));
  if (!sentences.length) return false;
  if (sentences.every((s) => s.endsWith("?"))) return true;
  // Only when the answer opens with it, after at most a short courtesy or softener: "Sure! Could you
  // tell me which city?" and "Sarah, could you tell me which order?" ask back; "To get
  // a refund, please provide your receipt." answers.
  const leads = [sentences[0]];
  if (sentences.length > 1 && sentences[0].split(" ").length <= 4) {
    if (sentences.slice(1).every((s) => s.endsWith("?"))) return true; // "Happy to help! Which product do you mean?"
    leads.push(sentences[1]);
  }
  const comma = sentences[0].indexOf(", ");
  if (comma >= 0 && sentences[0].slice(0, comma).split(" ").length <= 3) leads.push(sentences[0].slice(comma + 2));
  return leads
    .map((lead) => { const w = SOFTENERS.find((x) => lead.startsWith(x)); return w ? lead.slice(w.length) : lead; })
    // "I can't determine the exact date, but historians place it around 1200 BC." answers;
    // "I cannot determine your location, but you can check a map." does not.
    .some((lead) => NON_ANSWER_PHRASES.some((phrase) => lead.startsWith(phrase) && !(phrase.includes("determine") && answersAfterBut(lead))));
}

function answersAfterBut(lead) {
  const at = lead.indexOf(", but ");
  return at >= 0 && !REDIRECTS.some((r) => lead.slice(at + 6).startsWith(r));
}

// What _recordModelTurn did with an answer; the two that put it in the shared cache.
const STORED = new Set(["saved", "template"]);

class TurnDecision {
  constructor(action, { text = null, audio = null, confidence = 0, reason = "" } = {}) {
    this.action = action;
    this.text = text;
    this.audio = audio;
    this.confidence = confidence;
    this.reason = reason;
    // For a model turn: what the model must read, and whether its answer is shared.
    // null means "the whole call", and then the answer is never shared.
    this.messages = null;
    this.cacheable = false;
    // Which turn of the call this is; an answer recorded for an older turn is dropped.
    this.turn = 0;
    // After answer(): whether the model's answer was stored, and if not, why.
    this.stored = false;
    this.notStored = "";
    // Not enumerable: read through `empty`, never set by callers or copied out with the decision.
    Object.defineProperty(this, "_empty", { value: false, writable: true, enumerable: false });
    Object.defineProperty(this, "_audioShareable", { value: false, writable: true, enumerable: false });
    // Set by decide(): the session that made it (a WeakRef, so a kept decision never
    // keeps a call alive) and, for a model turn, what the caller said, so record()
    // takes a decision only from its own session, and only once. Not enumerable, so a
    // logged or serialised decision never carries them; the caller's words are dropped
    // once recorded.
    Object.defineProperty(this, "_session", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_said", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_recorded", { value: false, writable: true, enumerable: false });
  }

  /** Whether the spoken audio of this answer may go to the shared audio cache: not for an answer filled with this caller's values. */
  get audioShareable() {
    return this._audioShareable;
  }

  get servedFromCache() {
    return this.action === "serve";
  }

  get servedFromFiller() {
    return this.action === "filler";
  }

  get needsModel() {
    return this.action === "infer";
  }

  /** After answer(): the model was asked and said nothing (the action stays "infer"); retry, or speak a fallback. */
  get empty() {
    return this._empty;
  }

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
  }
}

// What VoiceSession.respond() resolves to: read it with `for await` for the text to
// speak, piece by piece as the model writes it. `decision` is ready at once, before the
// first piece: decision.servedFromCache and decision.audio say whether a cached answer
// (and its audio) can be played instead of running the TTS. A response is read once.
class VoiceResponse {
  constructor(session, decision, callerSaid, llm, system, keep) {
    this.decision = decision;
    for (const [name, value] of Object.entries({ session, callerSaid, llm, system, keep })) {
      Object.defineProperty(this, `_${name}`, { value, enumerable: false });
    }
    Object.defineProperty(this, "_pieces", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_closed", { value: false, writable: true, enumerable: false });
  }

  [Symbol.asyncIterator]() {
    if (this._pieces) throw new Error("a VoiceResponse is read once");
    this._pieces = this._run();
    return this._pieces;
  }

  // Stop early: the model's stream is closed and nothing is stored.
  async close() {
    this._closed = true;
    if (!this._pieces) {
      this._pieces = (async function* () {})();
      return;
    }
    await this._pieces.return();
  }

  // The caller talked over this turn, a newer turn was decided, or the app recorded the
  // turn itself: speak no more of this answer.
  _stopped() {
    return this.decision._recorded || this._session._movedOn(this.decision);
  }

  async *_run() {
    const session = this._session;
    const decision = this.decision;
    if (!decision.needsModel) {
      if (decision.text) yield decision.text;
      return;
    }
    if (this._stopped()) {
      // Talked over before a word was read: never call the model.
      session._interrupted(decision, "");
      return;
    }
    // As answer() does, so a subclass whose decide() returns its own decision works.
    decision._said = this._callerSaid;
    let messages = decision.messages || [...session.injections(), { role: "user", content: this._callerSaid }];
    if (this._system) messages = [{ role: "system", content: this._system }, ...messages];
    let source = await this._llm(messages);
    if (typeof source === "string" || source instanceof String) source = [String(source)];
    let upstream;
    if (source && typeof source[Symbol.asyncIterator] === "function") upstream = source[Symbol.asyncIterator]();
    else if (source && typeof source[Symbol.iterator] === "function") upstream = source[Symbol.iterator]();
    else throw new TypeError("respond() expects the model to give text: a string, or an (async) iterable of text pieces");
    const parts = [];
    let ended = false;
    let movedOn = false;
    try {
      for (;;) {
        const { value: piece, done } = await upstream.next();
        if (done) {
          ended = true;
          break;
        }
        if (piece === null || piece === undefined) continue;
        if (typeof piece !== "string") {
          throw new TypeError(
            `respond() expects the model to give text pieces (strings), got ${typeof piece}; map each chunk to its text first`
          );
        }
        if (this._stopped()) {
          movedOn = true;
          break;
        }
        parts.push(piece);
        if (piece) yield piece;
      }
    } finally {
      if (!ended && typeof upstream.return === "function") {
        try {
          await upstream.return();
        } catch {
          // the model's stream failed to close; nothing of it is kept either way
        }
      }
      if (movedOn) {
        session._interrupted(decision, parts.join(""));
      } else if (ended && !this._closed && !decision._recorded) {
        // A full answer is recorded under answer()'s rules.
        await session._recordDecision(decision, parts.join(""), this._keep, this._system);
      }
    }
  }
}

class VoiceSession {
  constructor(
    agent,
    {
      voice,
      serveAbove = 0.92,
      minWords = 3,
      synthesise,
      ttl,
      latencyBudgetMs,
      fillers,
      values,
      commitments = "exact",
      shortTurns = false,
      shareTemplates = false,
      language = "und",
      speed = "1",
      audioFormat = "default",
      bytesPerSecond,
    } = {}
  ) {
    if (!(serveAbove >= 0 && serveAbove <= 1)) {
      throw new Error(`serveAbove must be in 0..1, got ${serveAbove}`);
    }
    if (!Object.prototype.hasOwnProperty.call(COMMITMENTS, commitments)) {
      throw new Error(
        `commitments must be one of ${Object.keys(COMMITMENTS).sort().join(", ")}, got ${commitments}`
      );
    }
    if (latencyBudgetMs !== undefined && latencyBudgetMs !== null && !(latencyBudgetMs > 0)) {
      throw new Error(`latencyBudgetMs must be positive, got ${latencyBudgetMs}`);
    }
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "VoiceSession requires a voice id. Cached audio is only reusable for the " +
          "voice that produced it, and switching voices mid-call is audible"
      );
    }
    this.agent = agent;
    this.voice = voiceId;
    // What changes the sound besides the voice: a clip is reused only when all match (Voice add-on).
    this.language = language;
    this.speed = speed;
    this.audioFormat = audioFormat;
    this.bytesPerSecond = bytesPerSecond;
    this._reported = {};
    this.serveAbove = serveAbove;
    this.minWords = minWords;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.commitments = commitments;
    this.shortTurns = Boolean(shortTurns);
    // Off by default: a template is cut from an answer the model wrote with the whole
    // call in view, so what is left outside its slots can hold what the caller said.
    this.shareTemplates = Boolean(shareTemplates);
    this.values = Object.create(null);
    this.transcript = [];
    this.served = 0;
    this.inferred = 0;
    this.filled = 0;
    this.refusedShort = 0;
    this.refusedPrivate = 0;
    this.uncacheablePersonal = 0;
    this.overBudget = 0;
    this.bargeIns = 0;
    this.lookupErrors = 0;
    this.learnErrors = 0;
    // Writes the turn stopped waiting for at the latency budget (they finish in the background).
    this.slowWrites = 0;
    // Hits refused because the stored answer was saved for a different question.
    this.differentQuestion = 0;
    this.notShareable = 0;
    this.heldCommitments = 0;
    this.unspeakable = 0;
    this.emptyAnswers = 0;
    this.audioUnavailable = 0;
    // The question the latest stored answer was stored under.
    this._lastStored = null;
    this._fillers = new Map();
    this._open = false;
    this._cancelled = false;
    this._turnMark = 0;
    this._turn = 0;
    // [turn, whether that turn's answer may be shared]: read with the turn it belongs
    // to, so a decide() that finishes after a newer one never lends the newer turn its
    // flag (two decide() calls in flight at once). Same as Python's _shareable.
    this._shareable = [0, false];
    // Set once the caller tells the call something a later answer may depend on;
    // from then on nothing in this call is looked up or shared.
    this._tainted = false;
    // Caller turns _heard() has already checked (history is re-read every turn).
    this._heardTexts = new Set();
    if (values) this.setValues(values);
    if (fillers) this.registerFillers(fillers);
  }

  setValues(values = {}) {
    for (const [name, value] of Object.entries(values)) {
      if (value === null || value === undefined) delete this.values[name];
      else this.values[name] = String(value);
    }
  }

  registerFiller(trigger, response) {
    const key = normalise(trigger);
    if (!key) throw new Error("a filler trigger must contain something to match on");
    if (!(typeof response === "string" && response.trim())) {
      throw new Error("a filler response must not be empty");
    }
    this._fillers.set(key, response);
  }

  registerFillers(pairs = {}) {
    for (const [trigger, response] of Object.entries(pairs)) {
      this.registerFiller(trigger, response);
    }
  }

  async decide(callerSaid) {
    this._turn += 1;
    const turn = this._turn;
    const decision = await this._decide(callerSaid);
    decision.turn = turn;
    decision._session = new WeakRef(this);
    if (decision.needsModel) {
      decision._said = callerSaid;
      [decision.messages, decision.cacheable] = this._modelMessages(callerSaid);
    }
    // A newer turn's flag is never overwritten by an older one.
    if (turn === this._turn) this._shareable = [turn, decision.cacheable];
    return decision;
  }

  // What the model should read to answer this turn, and whether that answer may
  // be cached. A shared answer is only safe when the model saw nothing but the
  // cache key: the question, and for a follow-up the questions it leans on.
  // Personal turns, and follow-ups to one, get the whole call and are never shared.
  _modelMessages(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (
      this._tainted || text.split(/\s+/).filter(Boolean).length < this.minWords || isPersonal(text) || lookupOnly(text) ||
      this._afterUrgent(text) || unfinished(text)
    ) {
      return [null, false];
    }
    if (!isContextDependent(text)) {
      // "Twelve years old.": a turn that neither asks nor requests anything is an
      // answer about the caller, never stored on its own.
      if (!asks(text)) return [null, false];
      return [[{ role: "user", content: callerSaid }], true];
    }
    const chain = this._chain();
    if (chain === null || privateChain(chain, this.minWords)) return [null, false];
    return [[...chain, callerSaid].map((turn) => ({ role: "user", content: turn })), true];
  }

  async _decide(callerSaid) {
    this._turnMark = this.transcript.length;
    this._open = true;
    this._cancelled = false;

    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (!text) {
      this.refusedShort += 1;
      return new TurnDecision("infer", { reason: "empty transcript" });
    }

    const filler = this._fillers.get(normalise(text));
    if (filler !== undefined) {
      this.filled += 1;
      const decision = new TurnDecision("filler", {
        text: filler,
        audio: await this._voiced(filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
      });
      decision._audioShareable = true;
      return decision;
    }

    if (this._tainted || setsContext(text)) {
      this._tainted = true;
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the caller has told this call something a later answer may depend on " +
          "(a condition, an age, a plan, an instruction, a step in their own task); " +
          "a shared answer to the bare question could be wrong for them",
      });
    }

    // "Thank you" or "hello" is too short to match on meaning. With shortTurns
    // on it is served on an exact match the server's decision engine has
    // vouched for; otherwise, and with no engine, it goes to the model as it
    // always did.
    const short = text.split(/\s+/).length < this.minWords;
    if (short && !(this.shortTurns && (await this._engineVouches()))) {
      this.refusedShort += 1;
      return new TurnDecision("infer", {
        reason: "transcript too short to match safely",
      });
    }

    // A cut-off question ("do you deliver on") is near a full one ("...on Sundays") in meaning
    // but asks something else: never served a stored answer, never stored.
    if (unfinished(text)) {
      this.refusedShort += 1;
      return new TurnDecision("infer", { reason: "the turn was cut off mid-question" });
    }

    const personal = isPersonal(text);
    if (personal && !this._hasValues()) {
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the caller asked about their own records and this session has no values " +
          "to fill a shared answer shape with, so nothing can be answered from " +
          "cache without one caller's answer reaching the next",
      });
    }

    const contextBound = isContextDependent(text);
    const keyed = this._contextKey(callerSaid, text);
    if (keyed === null) {
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "the utterance only has meaning against an earlier turn and this call " +
          "has none, so no cache key can be built for it",
      });
    }
    if ((contextBound && privateChain(this._chain() || [], this.minWords)) || this._afterUrgent(text)) {
      this.refusedPrivate += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason:
          "a follow-up to a private turn of this call: its answer depends on what " +
          "this caller said, so it is never answered from a shared cache",
      });
    }

    let hit;
    const started = performance.now();
    try {
      const lookup = this.agent.ask(keyed, {
        serveAbove: this.serveAbove,
        cheapAbove: Math.min(0.6, this.serveAbove),
        template: personal,
        threshold: contextBound || short ? CONTEXT_BOUND_THRESHOLD : undefined,
      });
      const budgeted = this.latencyBudgetMs !== undefined && this.latencyBudgetMs !== null;
      hit = budgeted ? await within(this.latencyBudgetMs, lookup) : await lookup;
      // Cut off a slow lookup, and refuse one that finished after the budget.
      if (hit === LATE || (budgeted && performance.now() - started > this.latencyBudgetMs)) {
        lookup.catch(() => {});
        this.overBudget += 1;
        this.inferred += 1;
        return new TurnDecision("infer", {
          reason:
            `lookup passed the ${this.latencyBudgetMs}ms voice budget; ` +
            "a late hit is worse than a fast miss",
        });
      }
    } catch (error) {
      // An unreachable or refusing cache means "ask the model", never silence.
      this.lookupErrors += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        reason: `cache unavailable (${error && error.name}); asking the model`,
      });
    }

    if (hit.route !== "cache") {
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason: `confidence below the spoken-answer bar of ${this.serveAbove}`,
      });
    }

    let answer = hit.answer;
    if (personal) {
      answer = fill(answer, this.values);
      if (answer === null) {
        this.refusedPrivate += 1;
        this.inferred += 1;
        return new TurnDecision("infer", {
          confidence: hit.confidence,
          reason:
            "the shared answer shape has a slot this call has no value for; " +
            "speaking a half-filled answer is worse than a model call",
        });
      }
    }

    if (!personal && !hit.exact && (await this._answersAnotherQuestion(keyed, answer))) {
      this.differentQuestion += 1;
      this.inferred += 1;
      return new TurnDecision("infer", {
        confidence: hit.confidence,
        reason:
          "the cached answer was saved for a different question (it asks about something " +
          "this one does not); a model call is better than a wrong answer",
      });
    }

    const held = this._held(hit, answer, short);
    if (held) {
      this.inferred += 1;
      return new TurnDecision("infer", { confidence: hit.confidence, reason: held });
    }

    this.served += 1;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: answer });
    const decision = new TurnDecision("serve", {
      text: answer,
      audio: await this._voiced(answer, { cacheable: !personal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
    decision._audioShareable = !personal;
    return decision;
  }

  /**
   * Whether the server judges what it caches, asked inside this call's budget:
   * a slow answer is a no for this turn, and is there for the next.
   */
  async _engineVouches() {
    const asked = this.agent.decides();
    if (this.latencyBudgetMs === undefined || this.latencyBudgetMs === null) return asked;
    const answer = await within(this.latencyBudgetMs, asked);
    return answer === LATE ? false : answer;
  }

  /** Why a confident hit still goes to the model, if it does. */
  _held(hit, answer, short) {
    if (short && !(hit.vouched && hit.exact)) {
      return (
        "a short turn is only answered from cache once the answer has been " +
        "judged to stand on its own, and this one has not"
      );
    }
    if (hit.commitment && !COMMITMENTS[this.commitments](hit)) {
      this.heldCommitments += 1;
      return (
        "the cached answer is a commitment (a price, a refund, a policy) and " +
        `commitments="${this.commitments}" does not allow speaking this match`
      );
    }
    if (!speakable(answer)) {
      this.unspeakable += 1;
      return "the cached answer was written for a screen (a link, code or markup)";
    }
    return null;
  }

  cancel() {
    if (!this._open) return false;
    this._open = false;
    this._cancelled = true;
    this.bargeIns += 1;
    this.transcript.length = this._turnMark;
    return true;
  }

  // Run one caller turn end to end: cache, or the model, then remember the answer.
  // `llm` is called with exactly the messages Crowkis chose for this turn: the
  // question alone (or with the question before it) when the answer may be shared,
  // the whole call when it may not. `system` is the app's own instructions, the
  // same for every caller, and is put first. The returned decision carries the
  // text to speak, from the cache or from the model, and `stored` / `notStored`
  // say whether the model's answer was cached and why not. A model that says
  // nothing sets `empty`: retry, or speak a fallback.
  async answer(callerSaid, llm, { system = null } = {}) {
    const decision = await this.decide(callerSaid);
    if (!decision.needsModel) return decision;
    let messages = decision.messages || [...this.injections(), { role: "user", content: callerSaid }];
    if (system) messages = [{ role: "system", content: system }, ...messages];
    // Straight to the recording step: answer() made this decision itself, so a
    // subclass whose decide() returns its own decision object keeps working.
    decision._said = callerSaid;
    return this._recordDecision(decision, await llm(messages), false, system);
  }

  // Save the answer to a turn you sent to your own model: decide(), then call the
  // model with decision.messages, then record(decision, its answer).
  //
  // The same rules as answer() decide what happens to it: shared with other callers
  // only when decide() said it may be (decision.cacheable), kept to this call
  // otherwise, and dropped when the caller talked over it (cancel()) or a newer turn
  // was decided since. `private: true` keeps a shareable answer to this call, e.g. one
  // built from a tool's result. Never rejects for the server: a refused write is
  // reported, not thrown.
  //
  // Resolves to `decision` with `text` set to the answer and stored / notStored /
  // empty filled in, as answer() does. Rejects for a decision this session did not
  // make, one that did not need the model (served from the cache or a filler), or one
  // already recorded.
  async record(decision, answer, { private: keep = false, system = null } = {}) {
    if (!(decision instanceof TurnDecision)) {
      throw new Error("record() takes the TurnDecision decide() returned");
    }
    if (decision._recorded) throw new Error("record() got a decision that was already recorded");
    const owner = decision._session ? decision._session.deref() : undefined;
    if (owner !== this) {
      throw new Error(
        decision._session
          ? "record() got a decision from another session: each call's answers are recorded in the session that decided them"
          : "record() takes a decision from this session's decide(); one from another session (another call) or made by hand is refused"
      );
    }
    if (!decision.needsModel) {
      throw new Error(
        `record() is for a turn that needed the model; this one was answered by ${
          decision.servedFromFiller ? "a filler" : "the cache"
        } ("${decision.action}")`
      );
    }
    return this._recordDecision(decision, answer, keep, system);
  }

  // record() and answer(): store the answer and fill in the decision.
  async _recordDecision(decision, answer, keep, system = null) {
    decision._recorded = true;
    const said = decision._said;
    decision._said = null;
    decision.text = answer;
    const { outcome, why: reason } = await this._record(said, answer, {
      turn: decision.turn,
      private: keep,
      instructions: system,
    });
    decision.stored = STORED.has(outcome);
    const why = decision.stored ? "" : reason || outcome;
    decision.notStored = why;
    if (!(typeof decision.text === "string" && decision.text.trim())) {
      decision._empty = true;
      decision.reason = "the model returned an empty answer; retry or speak a fallback";
    } else if (why) {
      decision.reason = `${decision.reason}; not stored: ${why}`;
    }
    return decision;
  }

  // answer(), streamed: decide now, then give the text to speak piece by piece.
  //
  // llm(messages) gives the model's text as it writes it: an async iterable or iterable
  // of strings (null pieces are skipped), or the whole answer as a string (or a promise
  // of one). It is called with the same messages answer() would use, only when the turn
  // needs the model, and only once the response is read.
  //
  // A turn the cache or a filler answers yields that text once (decision.audio has its
  // audio when the session caches audio). A model turn yields the model's pieces and,
  // when its stream ends, records the full answer under answer()'s rules (`private` as
  // in record()). If the caller talks over it (cancel()) or a newer turn is decided, the
  // stream stops at the next piece, the model's stream is closed and nothing is stored.
  // A model error rejects and stores nothing, as does stopping early (close(), or
  // leaving the loop); the decision can then still be recorded with record().
  async respond(callerSaid, llm, { system = null, private: keep = false } = {}) {
    const decision = await this.decide(callerSaid);
    return new VoiceResponse(this, decision, callerSaid, llm, system, keep);
  }

  // Which agent's system prompts this call's is compared with.
  _agentKey() {
    const agent = this.agent || {};
    return [agent.tenant || (agent.client && agent.client.tenant) || null, agent.agentId || null];
  }

  // The caller talked over this turn, or a newer turn has been decided.
  _movedOn(decision) {
    return this._cancelled || decision.turn !== this._turn;
  }

  // A streamed turn the caller talked over: report it, store and keep nothing. Not an
  // empty answer, so an app never retries over the caller's new words.
  _interrupted(decision, spoken) {
    if (decision._recorded) return;
    decision._recorded = true;
    decision._said = null;
    decision.text = spoken;
    decision.stored = false;
    decision.notStored = "the caller moved on before this answer was complete";
    decision.reason = `${decision.reason}; not stored: ${decision.notStored}`;
  }

  // Keep a turn in this call's transcript and never cache it. For a model that
  // holds the whole conversation itself (a realtime speech model): it cannot be
  // given decision.messages, so nothing it says is shared.
  recordPrivateTurn(callerSaid, modelSaid) {
    this._heard(callerSaid);
    if (this._cancelled) return;
    this._open = false;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (this._shareable[1]) this.notShareable += 1;
    this._shareable = [0, false];
  }

  // Note, in the background, that `answer` was saved for `question`. A failure only means a
  // later hit can't be checked, which is how it was before.
  _keepQuestion(question, answer) {
    const client = this.agent && this.agent.client;
    if (!client || typeof client.set !== "function") return;
    const key = questionKey(tenantOf(this.agent), answer);
    const ttl = this.ttl;
    storeLater(async () => {
      try {
        const raw = await client.get(key);
        let kept = raw ? JSON.parse(String(raw)) : [];
        kept = (Array.isArray(kept) ? kept : []).filter((q) => typeof q === "string" && q !== question).slice(-(QUESTIONS_KEPT - 1));
        await client.set(key, JSON.stringify([...kept, question]), ttl === undefined || ttl === null ? {} : { ttl });
      } catch {
        // see above
      }
    });
  }

  // Whether every question this answer was saved for asks about something else. Unknown
  // (no record, or it can't be read in time) means no: as before.
  async _answersAnotherQuestion(asked, answer) {
    const client = this.agent && this.agent.client;
    if (!client || typeof client.get !== "function") return false;
    try {
      const read = Promise.resolve().then(() => client.get(questionKey(tenantOf(this.agent), answer)));
      read.catch(() => {});
      const budgeted = this.latencyBudgetMs !== undefined && this.latencyBudgetMs !== null;
      const raw = budgeted ? await within(this.latencyBudgetMs, read) : await read;
      if (raw === LATE || !raw) return false;
      const questions = JSON.parse(String(raw));
      if (!Array.isArray(questions)) return false;
      const kept = questions.filter((q) => typeof q === "string");
      return kept.length > 0 && kept.every((q) => differentSpecifics(asked, q));
    } catch {
      return false;
    }
  }

  // agent.learn(), waited for no longer than twice the latency budget: a slow server never
  // stalls the turn after a miss. A write still running then finishes in the background
  // (an error it ends with is counted). An error within the budget is thrown, as before.
  // Without a budget it is waited for, as it always was. False when the turn stopped waiting.
  //
  // Resolves to null when the write is done; otherwise to the "slow_write" outcome to
  // report (still running, or not written at all because too many writes wait).
  async _learn(...args) {
    if (this.latencyBudgetMs === undefined || this.latencyBudgetMs === null) {
      await this.agent.learn(...args);
      return null;
    }
    if (pendingWrites.size >= WRITES_MAX) {
      this.slowWrites += 1;
      console.warn("crowkis voice: too many writes waiting on a slow server; this answer is not written");
      return { outcome: "slow_write", why: "not written: too many writes are waiting on a slow server" };
    }
    let late = false; // set by the timer itself, so an error at any later moment is counted here
    const write = Promise.resolve().then(() => this.agent.learn(...args));
    const tracked = write
      .catch((error) => {
        if (!late) return; // before the turn stopped waiting: thrown to the caller, counted there
        this.learnErrors += 1;
        console.warn(`crowkis voice: a write that passed the latency budget then failed (${(error && error.name) || "Error"})`);
      })
      .finally(() => pendingWrites.delete(tracked));
    pendingWrites.add(tracked);
    const finished = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        late = true;
        resolve(false);
      }, 2 * this.latencyBudgetMs);
      write.then(
        () => { clearTimeout(timer); resolve(true); },
        (error) => { clearTimeout(timer); if (!late) reject(error); }
      );
    });
    if (finished) return null;
    this.slowWrites += 1;
    return { outcome: "slow_write", why: "not confirmed: the server took longer than the latency budget, so the write finishes in the background" };
  }

  // A caller turn this session never decided (a private turn, history the app gave the
  // model): one that tells the call something a later answer may depend on keeps the
  // rest of the call off the shared cache, as decide() does for its own turns.
  _heard(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (this._tainted || !text || this._heardTexts.has(text)) return;
    if (this._heardTexts.size < HEARD_MAX) this._heardTexts.add(text);
    if (setsContext(text)) this._tainted = true;
  }

  // Record the model's answer to the turn decide() last handled, and cache it if
  // allowed. Only an answer written from decision.messages reaches this, so it is
  // shared exactly when decide() said it may be. `turn` is the decision's turn: an
  // answer to a turn the caller talked over, or to one before the latest, is
  // dropped, so it never lands on later words. Never rejects: a refused write
  // (security pipeline, tenant limit, cache down) must not end a call.
  //
  // Resolves to what happened to the answer: "saved" (shared), "template" (shared
  // as a shape, this caller's values removed), "kept" (the model read the whole
  // call, so it stays in this call), "private" (personal, or repeats this caller's
  // details), "non_answer", "not_saved" (a follow-up with nothing to key it to),
  // "refused" (the write failed), "slow_write" (a session with a latency budget stopped
  // waiting for the write: not confirmed) or "interrupted" (talked over, or the caller
  // moved on before it was complete).
  async _recordModelTurn(callerSaid, modelSaid, { turn, private: keep = false } = {}) {
    return (await this._record(callerSaid, modelSaid, { turn, private: keep })).outcome;
  }

  // The same, with why an answer was not stored, in words.
  async _record(callerSaid, modelSaid, { turn, private: keep = false, instructions = null } = {}) {
    const outcome = (word, why = "") => ({ outcome: word, why });
    if (this._cancelled || (turn !== undefined && turn !== null && turn !== this._turn)) {
      return outcome("interrupted", "the caller moved on before this answer was complete");
    }
    this._open = false;
    const expected = turn === undefined || turn === null ? this._turn : turn;
    const shareable = this._shareable;
    this._shareable = [0, false];
    const cacheable = shareable[1] && shareable[0] === expected;
    if (!(typeof modelSaid === "string" && modelSaid.trim())) {
      this.emptyAnswers += 1;
      return outcome("non_answer", "the model returned an empty answer");
    }
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    const keyed = this._contextKey(callerSaid, text);
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (keyed === null) return outcome("not_saved", "a follow-up with no earlier turn to key it on");
    if (keep) {
      this.notShareable += 1;
      return outcome("kept", "kept to this call: the answer was built from a tool's result");
    }
    if (instructions && repeatsPromptDetails(modelSaid, text, instructions, this._agentKey())) {
      // The model read a system prompt that names this caller, and its answer repeats
      // that: right for this caller only, never a shared answer or template.
      this.notShareable += 1;
      return outcome("private", "kept to this call: the answer repeats a detail about the caller from the system prompt");
    }
    try {
      if (isPersonal(text)) {
        if (!this._tainted && !isNonAnswer(modelSaid) && !unfinished(text)) {
          const templated = await this._learnPersonal(keyed, modelSaid);
          if (templated && templated.outcome) return templated; // slow_write: the shape was not confirmed written
          if (templated) return outcome("template");
        }
        return outcome("private", "about this caller, with no declared value to make a shared answer shape from");
      }
      if (this._tainted) {
        this.notShareable += 1;
        return outcome("kept", "kept to this call: the caller told it something the answer may depend on");
      }
      if (!cacheable) {
        this.notShareable += 1;
        return outcome("kept", "kept to this call: the answer depends on what this caller said");
      }
      if (leaks(modelSaid, this.values)) {
        this.notShareable += 1;
        return outcome("private", "kept to this call: the answer contains a value declared for this call");
      }
      if (isNonAnswer(modelSaid)) {
        this.notShareable += 1;
        return outcome("non_answer", "not saved: the answer asks back or does not answer");
      }
      const slow = await this._learn(keyed, modelSaid, { ttl: this.ttl });
      this._lastStored = keyed;
      if (!slow) this._keepQuestion(keyed, modelSaid); // a slow server gets no extra write
      return slow || outcome("saved");
    } catch (error) {
      this.learnErrors += 1;
      return outcome(
        "refused",
        `the server refused the write: ${(error && error.message) || (error && error.name) || String(error)}`
      );
    }
  }

  injections() {
    return this.transcript.slice();
  }

  /** The counts the Voice page shows, by the server's names. */
  _reportable() {
    return {
      turns: this.served + this.inferred + this.filled,
      served_from_cache: this.served,
      filler_hits: this.filled,
      model_calls_avoided: this.served + this.filled,
      private_turns: this.refusedPrivate + this.uncacheablePersonal,
      barge_ins: this.bargeIns,
      latency_misses: this.overBudget,
      empty_answers: this.emptyAnswers,
    };
  }

  /**
   * Send this session's counts since its last report to the Voice page (the server's Voice add-on).
   * false when the server has no Voice add-on. Nothing is lost: what a failed report did not send
   * goes with the next.
   */
  async reportStats() {
    const now = this._reportable();
    const sent = {};
    for (const [name, count] of Object.entries(now)) {
      const fresh = count - (this._reported[name] || 0);
      if (fresh > 0) sent[name] = Math.min(fresh, REPORT_MAX);
    }
    if (!Object.keys(sent).length) return true;
    try {
      await this.agent.client.cvoicestat(sent, { tenant: this.agent.tenant });
    } catch (error) {
      if (voiceAddonMissing(error)) return false;
      throw error;
    }
    for (const [name, count] of Object.entries(sent)) this._reported[name] = (this._reported[name] || 0) + count;
    return true;
  }

  stats() {
    const total = this.served + this.inferred + this.filled;
    const pct = (count) => (total ? Math.round((10000 * count) / total) / 100 : 0);
    return {
      turns: total,
      servedFromCache: this.served,
      answeredByFiller: this.filled,
      modelCalls: this.inferred,
      refusedTooShort: this.refusedShort,
      refusedToShareAPrivateAnswer: this.refusedPrivate,
      uncacheablePersonal: this.uncacheablePersonal,
      missedLatencyBudget: this.overBudget,
      bargeIns: this.bargeIns,
      cacheUnavailable: this.lookupErrors,
      failedWrites: this.learnErrors,
      slowWrites: this.slowWrites,
      differentQuestion: this.differentQuestion,
      notShareable: this.notShareable,
      commitmentsSentToModel: this.heldCommitments,
      unspeakableAnswers: this.unspeakable,
      emptyAnswers: this.emptyAnswers,
      audioUnavailable: this.audioUnavailable,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
    };
  }

  _hasValues() {
    return Object.keys(this.values).length > 0;
  }

  // The earlier caller turns a follow-up leans on, oldest first: back to the
  // latest one that stands on its own. null when there is no such turn.
  _chain() {
    const chain = [];
    for (let index = this.transcript.length - 1; index >= 0; index -= 1) {
      const turn = this.transcript[index];
      if (turn.role !== "user") continue;
      chain.unshift(turn.content);
      if (!isContextDependent(typeof turn.content === "string" ? turn.content.trim() : "")) return chain;
      if (chain.length >= CHAIN_LIMIT) return null;
    }
    return null;
  }

  // A short turn after a private emergency or medical turn ("is he going to be
  // okay?", "how do i make her vomit?"): about that turn, so answered with the call.
  _afterUrgent(text) {
    if (wordsOf(text).length > FOLLOW_UP_WORDS) return false;
    const earlier = this.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    for (const said of earlier.slice(-CHAIN_LIMIT).reverse()) {
      const words = wordsOf(said);
      if ((words.some((w) => URGENT.has(w)) || urgent(words)) && isPersonal(said)) return true;
      if (words.length > FOLLOW_UP_WORDS) return false;
    }
    return false;
  }

  _contextKey(callerSaid, text) {
    if (!isContextDependent(text)) return callerSaid;
    const chain = this._chain();
    if (chain === null) return null;
    return [...chain, callerSaid].join(" || ");
  }

  // Store a personal answer as a shape. False when it cannot be made generic, or when
  // this session does not share templates.
  async _learnPersonal(keyed, modelSaid) {
    if (!this.shareTemplates) {
      this.uncacheablePersonal += 1;
      return false;
    }
    const shaped = abstract(modelSaid, this.values);
    // The model read the whole call: what is left outside the slots must say nothing
    // of this caller that was not declared (a name, an address, a number, a matter).
    const outside = shaped.replace(SLOT, " ");
    const words = wordsOf(outside);
    const earlier = this.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    const undeclared =
      words.some((w) => hasDigit(w) || AMOUNT_WORDS.has(w) || MATTERS.has(w)) ||
      readsOutDigits(outside, words) || EMAIL.test(outside) || identifies(outside, words) ||
      carriesCallContext(outside, keyed, earlier);
    if (this._hasValues() && slotNames(shaped).length && !leaks(shaped, this.values) && !undeclared) {
      return (await this._learn(keyed, shaped, { ttl: this.ttl, template: true })) || true;
    }
    this.uncacheablePersonal += 1;
    return false;
  }

  // The audio for an answer this turn speaks, or null. Never rejects: when the audio
  // step fails (the cache, or the app's own synthesiser) the turn keeps its text and the
  // app's TTS speaks it. It used to reject the whole turn, losing the cached answer.
  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    try {
      if (this.latencyBudgetMs === undefined || this.latencyBudgetMs === null) return await this._voice(answer, cacheable);
      // With a budget, a hung audio cache never holds the turn: past twice the budget the
      // text is served and the audio step (with its clip) finishes in the background.
      const voicing = this._voice(answer, cacheable);
      voicing.catch(() => {});
      const audio = await within(2 * this.latencyBudgetMs, voicing);
      if (audio === LATE) {
        this.audioUnavailable += 1;
        console.warn("crowkis voice: the audio step passed the latency budget; the text is served");
        return null;
      }
      return audio;
    } catch (error) {
      this.audioUnavailable += 1;
      // The type only: an app's TTS error can quote the (possibly personal) text.
      console.warn(`crowkis voice: no audio for this answer, the text is still served (${(error && error.name) || typeof error})`);
      return null;
    }
  }

  async _voice(answer, cacheable) {
    // A text-only session (voiceSession() with no voice) has no real voice id to key a
    // clip on: speak, but never read or store a cached clip.
    if (!cacheable || this._textOnly) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
      language: this.language,
      speed: this.speed,
      audioFormat: this.audioFormat,
      bytesPerSecond: this.bytesPerSecond,
    });
  }
}

/**
 * Fill the cache from past calls, so it is useful on the first day.
 *
 * `calls` is an iterable of calls, each an array of `[callerSaid, agentSaid]`
 * turns in order. A follow-up is kept with the turn it depends on, and nothing
 * is spoken or synthesised.
 *
 * It needs the server's decision engine, holding answers until it has judged
 * them (the default), and throws otherwise. A past agent turn can hold
 * details the caller never said aloud (an address looked up, a balance),
 * which the live rules cannot see in a transcript; the engine reads every
 * answer before anyone is served it.
 *
 * Resolves to totals. After each call it gives the engine up to `wait`
 * seconds to catch up; `stalled` is true when it stopped early because three
 * calls in a row were not judged in that time.
 */
async function warmFromCalls(agent, calls, { wait = 30 } = {}) {
  if (!((await agent.decides()) && agent._holds)) {
    throw new Error(
      "warmFromCalls needs the server's decision engine, holding answers until it has judged " +
        "them (CROWKIS_DECIDE_UPSTREAM set, CROWKIS_DECIDE_SERVE_UNJUDGED not set): otherwise a " +
        "past answer holding one caller's details could be shared before it is checked"
    );
  }
  const totals = { calls: 0, turns: 0, keptPrivate: 0, failedWrites: 0, stalled: false };
  let stalls = 0;
  for (const call of calls) {
    const session = new VoiceSession(agent, { voice: "warm-start" });
    const earlier = [];
    for (const [callerSaid, agentSaid] of call) {
      // The same rule as a live turn picks the candidates. A past answer was
      // written with the whole call in view, so one that repeats what
      // identified this caller is kept out here, and the engine reads the rest
      // before anyone is served them.
      const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
      const keyed = session._contextKey(callerSaid, text) || callerSaid;
      session._tainted = session._tainted || setsContext(text);
      session._shareable = [
        session._turn,
        session._modelMessages(callerSaid)[1] && !carriesCallContext(agentSaid, keyed, earlier),
      ];
      await session._recordModelTurn(callerSaid, agentSaid);
      earlier.push(callerSaid);
      totals.turns += 1;
    }
    totals.calls += 1;
    totals.keptPrivate += session.notShareable + session.uncacheablePersonal;
    totals.failedWrites += session.learnErrors;
    // Let the engine catch up before the next call: it judges a bounded
    // number of answers at a time and refuses what does not fit.
    stalls = (await judgedInTime(agent, session._lastStored, wait * 1000)) ? 0 : stalls + 1;
    if (stalls >= 3) {
      totals.stalled = true;
      break;
    }
  }
  return totals;
}

/** False when the engine was still working on `query` after `ms`. */
async function judgedInTime(agent, query, ms) {
  const deadline = Date.now() + ms;
  while (query && Date.now() < deadline) {
    let view;
    try {
      view = await agent.explain(query);
    } catch (_error) {
      // Cannot ask, so there is nothing to wait for.
      return true;
    }
    if (!(view && view.pending)) return true;
    await new Promise((resolve) => setTimeout(resolve, Math.min(200, ms)));
  }
  return !query;
}

// The voice id of a text-only session. Never used as a cache key: every audio path
// checks `_textOnly` first.
const TEXT_ONLY_VOICE = "crowkis:text-only";

// Every option new VoiceSession() takes, so a misspelt one is an error here, as in Python.
const SESSION_OPTIONS = new Set([
  "serveAbove", "minWords", "synthesise", "ttl", "fillers", "values", "commitments",
  "shortTurns", "shareTemplates", "language", "speed", "audioFormat", "bytesPerSecond",
]);

/**
 * A ready VoiceSession in one call, with defaults for live calls (same as Python's
 * crowkis.voice_session()).
 *
 * It builds the client and the Agent itself. Server settings not passed here come from
 * the environment, then the defaults (see the README, "Connect to your server"). The
 * defaults differ from a bare VoiceSession because a caller is waiting:
 * - latencyBudgetMs 250: the longest a turn waits for a cache lookup before it goes to
 *   the model. null turns the budget off.
 * - timeoutMs 1000 per server request, with no retries. Saving the model's answer
 *   happens while the caller waits; 5 s tried three times would leave a stuck server
 *   holding the turn for about 15 s. The cost of no retries: a request that fails once
 *   (the first after a server restart, or a BUSY reply) is not tried again, so that
 *   lookup goes to the model or that answer is not stored. Pass your own `client` for
 *   other settings, e.g. for warmFromCalls, which should not use this live-call client.
 *
 * `voice` is the TTS voice id. Without it the session caches text only and never reads
 * or stores audio, so two voices can never share a clip; passing `synthesise` then is
 * an error. Every other VoiceSession option is passed on as it is.
 *
 * `client` uses a client you built, as it is: passing host/port/authToken/token/tenant/
 * timeoutMs with it is an error, and closing the agent leaves it open.
 */
function voiceSession(options = {}) {
  const {
    voice,
    agentId = "voice",
    client: given,
    host,
    port,
    authToken,
    auth_token: authTokenAlias,
    token,
    tenant,
    timeoutMs,
    latencyBudgetMs = 250,
    ...rest
  } = options;
  if (timeoutMs !== undefined && timeoutMs !== null && !(timeoutMs > 0)) {
    throw new Error(`timeoutMs must be a positive number of milliseconds, got ${timeoutMs}`);
  }
  const unknown = Object.keys(rest).filter((name) => !SESSION_OPTIONS.has(name));
  if (unknown.length) {
    throw new TypeError(`voiceSession() got unknown option(s): ${unknown.join(", ")}`);
  }
  if (given) {
    const passed = Object.entries({ host, port, authToken, auth_token: authTokenAlias, token, tenant, timeoutMs })
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([name]) => name);
    if (passed.length) {
      throw new Error(
        `voiceSession() got client and ${passed.join(", ")}: a client passed in is used as it is, ` +
          "so set these on the client instead"
      );
    }
  }
  const textOnly = voice === undefined || voice === null;
  if (textOnly && rest.synthesise) {
    throw new Error(
      "voiceSession() got synthesise without voice. Cached audio is keyed on the voice that " +
        "spoke it: pass your TTS voice id, or leave out synthesise to cache text only"
    );
  }
  const client =
    given ||
    new CrowkisClient({
      host,
      port,
      authToken: authToken || authTokenAlias || token,
      tenant,
      timeoutMs: timeoutMs ?? 1000,
      maxRetries: 0,
    });
  const agent = new Agent(agentId, { client, tenant: client.tenant });
  agent._ownsClient = !given;
  const session = new VoiceSession(agent, {
    ...rest,
    voice: textOnly ? TEXT_ONLY_VOICE : voice,
    latencyBudgetMs,
  });
  session._textOnly = textOnly;
  return session;
}

module.exports = {
  VoiceSession,
  VoiceResponse,
  TurnDecision,
  voiceSession,
  warmFromCalls,
  _SESSION_OPTIONS: SESSION_OPTIONS,
  _speakable: speakable,
  _words: wordsOf,
  _promptDetails: promptDetails,
  _repeatsPromptDetails: repeatsPromptDetails,
  _callerDetails: callerDetails,
  _resetPromptBaselines: resetPromptBaselines,
  _differentSpecifics: differentSpecifics,
  _waitForWrites: waitForWrites,
  _setWritesMax: setWritesMax,
  _isPersonal: isPersonal,
  _isContextDependent: isContextDependent,
  _setsContext: setsContext,
  _tellsFacts: tellsFacts,
  _tellsAboutCaller: tellsAboutCaller,
  _instructs: instructs,
  _urgent: urgent,
  _wordsOf: wordsOf,
  _identifying: identifying,
  _properNouns: properNouns,
  _isNonAnswer: isNonAnswer,
  _abstract: abstract,
  _fill: fill,
};
