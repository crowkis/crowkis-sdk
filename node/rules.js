"use strict";

// The word rules every Crowkis conversation decision rests on: which turns are
// personal (never shared), which only mean something after the previous one
// (follow-ups), how a personal answer becomes a shape with slots, and which
// answers do not answer at all. Pure functions, no I/O. Identical in the Python
// SDK (crowkis/rules.py) and mirrored in the Crowkis server (cache/mod.rs);
// change all three together.

const TRIM = "\\s!-\\/:-@\\[-`{-~";

const TRIM_EDGES = new RegExp(`^[${TRIM}]+|[${TRIM}]+$`, "g");

const WORDS = /[\p{L}\p{N}]+/gu;

const SLOT = /\{([^{}\s]+)\}/g;

const CONTEXT_BOUND_THRESHOLD = 0.995;

const POSSESSIVES = new Set(["my", "our", "mine", "ours"]);

const HELD_RECORDS = new Set([
  "account", "order", "orders", "balance", "booking", "bookings",
  "reservation", "subscription", "payment", "payments", "invoice",
  "invoices", "refund", "delivery", "shipment", "ticket", "claim",
  "policy", "plan", "membership", "appointment", "prescription",
  "statement", "transaction", "transactions", "card", "loan", "mortgage",
  "benefits", "package", "parcel", "return", "returns", "profile",
  "password", "address", "phone", "email", "number", "contract",
  "renewal", "bill", "billing", "charge", "charges", "deposit",
  "withdrawal", "transfer", "case", "complaint", "name", "details",
  "detail", "info", "information", "points", "rewards", "cart", "basket",
  "wallet", "credit", "credits", "history", "purchase", "purchases",
  "username", "warranty", "coupon", "voucher", "code", "otp", "pin", "emi",
]);

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
];

const OWNER_PREPOSITIONS = new Set([
  "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
  "onto", "under", "via",
]);

const STATE_LEADS = new Set([
  "what", "whats", "when", "where", "which", "who", "how", "is", "are",
  "has", "have", "had", "did", "do", "does", "show", "tell", "check",
  "status",
]);

const CONNECTIVES = new Set(["and", "so", "but", "or", "also", "then"]);

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
const FOLLOW_UP_ENDINGS = new Set(["too", "also", "instead"]);

const ANAPHOR_PHRASES = ["this one", "the second one", "the first one", "the other one"];

const ANAPHORS = new Set(["that", "those", "it", "them", "they", "these", "this"]);

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
const CALLER_LEADS = [["as", "a"], ["as", "an"], ["i", "am"], ["i", "m"], ["for"]];
const SELF_PHRASES = [
  ["am", "i"], ["do", "i", "qualify"], ["i", "live", "in"], ["i", "am", "from"],
  ["i", "m", "from"], ["i", "am", "based"], ["i", "m", "based"], ["i", "am", "on"],
  ["i", "m", "on"],
];

// A caller describing themself makes the right answer theirs alone: "I'm a farmer", "I am 65", "I have a small business", "my income is low", "which scheme suits someone like me".
// Not an action or a feeling ("I'm looking for", "I'm not sure"), a filler ("I'm a bit"), a generic
// role ("as a customer"), a hypothetical ("if I am late"), or a service ("explain this for me").
const NOT_DESCRIPTION = new Set(["not", "so", "just", "sure", "unsure", "curious", "interested", "wondering", "confused", "able", "unable", "about", "going", "also", "still", "really", "very", "glad", "happy", "sorry", "ready", "done", "back", "here", "speaking"]);
const ARTICLE_FILLERS = new Set(["bit", "little", "lot", "few", "couple"]);
const GENERIC_ROLES = new Set(["customer", "customers", "user", "users", "buyer", "client", "guest", "visitor", "shopper"]);
const HAVE_NOT = new Set(["question", "questions", "query", "doubt", "quick", "general", "problem"]);
const HYPOTHETICAL = new Set(["if", "when", "whether", "unless", "once"]);
const SERVICE_VERBS = new Set(["explain", "describe", "list", "repeat", "check", "clarify", "define", "translate", "summarise", "summarize", "write", "read", "spell"]);
const LIFE_WORDS = new Set(["income", "salary", "age", "family", "wife", "husband", "son", "daughter", "kids", "children", "child", "parents", "mother", "father", "farm", "business", "company", "shop", "health", "condition", "disability", "pension", "loan", "debt", "religion", "caste"]);
const CIRCUMSTANCES = [["i", "have", "been"], ["i", "work", "as"], ["i", "work", "at"], ["i", "work", "in"], ["i", "work", "for"], ["i", "run", "a"], ["i", "own", "a"], ["i", "earn"], ["i", "was", "born"], ["i", "belong", "to"], ["i", "come", "from"], ["i", "stay", "in"], ["lost", "my", "job"], ["i", "got", "married"], ["we", "are", "a"], ["we", "re", "a"], ["we", "have", "a"], ["being", "a"], ["being", "an"], ["someone", "like", "me"], ["people", "like", "me"], ["in", "my", "case"], ["in", "my", "situation"], ["my", "situation"], ["my", "circumstances"], ["for", "my", "family"], ["for", "my", "age"]];

function describesSelf(words) {
  if (CIRCUMSTANCES.some((phrase) => contains(words, phrase))) return true;
  if (words.length > 2 && words[0] === "as" && (words[1] === "a" || words[1] === "an") && !GENERIC_ROLES.has(words[2])) {
    return true;
  }
  for (let i = 0; i < words.length; i += 1) {
    const word = words[i];
    const after = words.slice(i + 1);
    if (word === "my" && after.length && LIFE_WORDS.has(after[0])) return true;
    if (word === "me" && i > 0 && words[i - 1] === "for") {
      if (!words.slice(Math.max(0, i - 6), i - 1).some((w) => SERVICE_VERBS.has(w))) return true;
    }
    if (i > 0 && HYPOTHETICAL.has(words[i - 1])) continue;
    if (word === "i" && after.length >= 3 && after[0] === "have" && (after[1] === "a" || after[1] === "an") && !HAVE_NOT.has(after[2])) {
      return true;
    }
    if (word === "i" && after.length >= 2 && (after[0] === "am" || after[0] === "m")) {
      const x = after[1];
      if (x === "a" || x === "an" || x === "the") {
        if (after.length >= 3 && !ARTICLE_FILLERS.has(after[2]) && !GENERIC_ROLES.has(after[2])) return true;
      } else if (/^[0-9]+$/.test(x) || (!x.endsWith("ing") && !NOT_DESCRIPTION.has(x))) {
        return true;
      }
    }
  }
  return false;
}

function describesCaller(words) {
  if (describesSelf(words) || SELF_PHRASES.some((phrase) => contains(words, phrase))) return true;
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

function ownedRecordAt(words) {
  for (let index = 0; index < words.length; index += 1) {
    if (!POSSESSIVES.has(words[index])) continue;
    for (const near of words.slice(index + 1, index + 3)) {
      if (HELD_RECORDS.has(near)) return index;
    }
  }
  return -1;
}

function isStateInterrogative(words) {
  return STATE_LEADS.has(words[0]) || words.includes("status");
}

// --- Turns whose answer must never be shared ------------------------------------------
// Kept word for word with the Python SDK (voice.py) and the server (cache/mod.rs
// `never_share`). Each group fails closed: a match means "answer fresh, never cache".

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
const EMAIL_ENDINGS = new Set(["com", "in", "org", "net", "co", "io"]);
const ACTION_VERBS = new Set([
  "cancel", "book", "reschedule", "change", "update", "delete", "remove", "send", "text",
  "email", "call", "connect", "transfer", "escalate", "refund", "replace", "exchange",
  "return", "speak", "talk", "process", "block", "unblock", "check", "track", "add",
  "apply", "upgrade", "downgrade", "activate", "deactivate", "close", "open", "resend",
]);
// A verb first is a request only when it acts on something the caller points at
// ("cancel my order", "send me the invoice"). A bare verb is search-style phrasing:
// "refund status for john", "send events to an endpoint".
const ACTION_OBJECTS = new Set(["me", "my", "it", "this", "that", "us", "our", "the", "them"]);
// After these leads, an action verb is a request for the agent to do something.
const ACTION_LEADS = [
  ["please"], ["can", "you"], ["could", "you"], ["will", "you"], ["would", "you"],
  ["i", "want", "to"], ["i", "d", "like", "to"], ["i", "would", "like", "to"],
  ["i", "need", "to"], ["let", "me"], ["i", "wanna"],
];
// Replies to the agent, not questions: a reply word first (or "okay" + a reply word),
// and no wh-question word anywhere.
const REPLY_LEADS = new Set(["yes", "yeah", "yep", "yup", "no", "nope", "nah", "correct", "exactly", "sure"]);
const SOFT_REPLY_LEADS = new Set(["okay", "ok", "alright", "fine", "right"]);
const REPLY_FOLLOWERS = new Set(["go", "please", "thanks", "thank", "that"]);
const WH_WORDS = new Set(["how", "what", "when", "where", "which", "who", "why"]);
const SINGLE_WORDS = new Set([
  // live data
  "today", "tonight", "currently", "outage", "queue",
  // memory of this call
  "remember",
  // dialogue and complaints
  "pardon", "louder", "slower", "slowly", "ridiculous", "frustrated", "frustrating",
  "angry", "upset", "worst", "terrible", "unacceptable", "disappointed",
  // steering
  "pretend", "ignore", "roleplay",
  // sensitive advice
  "pregnancy", "pregnant", "breastfeeding", "allergic", "allergy", "allergies",
  "medicine", "medication", "dosage", "doctor", "symptoms", "sue", "lawsuit",
  "lawyer", "legal", "invest", "investment",
  // abuse
  "stupid", "idiot", "useless", "dumb", "shit", "damn", "hell", "crap", "fuck",
  "fucking", "bullshit", "bloody",
  // identity checks
  "otp", "cvv",
  // Hinglish possessives and first person
  "mera", "meri", "mere", "maine", "mujhe", "hamara", "hamari",
  // handing over to a person, Hinglish "I am"
  "supervisor", "hoon", "hun",
]);
const NEVER_PHRASES = [
  // self-introduction
  ["my", "name"], ["name", "s"], ["call", "me"], ["i", "m", "called"],
  // memory of this call
  ["did", "i", "tell"], ["did", "i", "say"], ["did", "i", "just"], ["i", "told", "you"],
  ["as", "i", "said"], ["i", "mentioned"], ["who", "i", "am"], ["have", "i"],
  // things the caller did
  ["i", "ordered"], ["i", "bought"], ["i", "paid"], ["i", "placed"], ["i", "received"],
  ["i", "purchased"], ["i", "returned"], ["i", "booked"], ["i", "cancelled"], ["i", "canceled"],
  ["i", "was", "charged"], ["i", "got", "charged"], ["i", "haven", "t"], ["i", "didn", "t"],
  ["charged", "twice"], ["double", "charged"],
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
  ["for", "this", "call"], ["for", "the", "rest"], ["tell", "everyone"], ["your", "rules"],
  ["your", "instructions"], ["previous", "instructions"], ["system", "prompt"],
  // sensitive advice
  ["safe", "during"], ["safe", "for", "kids"],
  // Indian-English and Hinglish introductions, personal fit, hand-over, steering
  ["this", "side"], ["bol", "raha"], ["bol", "rahi"], ["name", "you", "have"], ["have", "for", "me"], ["suit", "me"], ["suits", "me"], ["me", "best"], ["put", "me", "through"], ["transfer", "me"], ["connect", "me"], ["from", "here", "on"], ["call", "yourself"],
  // the caller's own purchases and payments
  ["did", "i", "order"], ["did", "i", "buy"], ["did", "i", "pay"], ["did", "i", "purchase"], ["did", "i", "get"], ["i", "ordered"], ["i", "bought"], ["i", "purchased"], ["i", "paid"], ["last", "time", "i"],
];
const DIGITS = /[0-9]{5,}/;
const EMAIL = /[A-Za-z0-9._%+-]@[A-Za-z0-9-]/;

function startsWith(words, at, phrase) {
  return phrase.every((w, k) => words[at + k] === w);
}

// Whether a turn's answer must never be shared, whatever the rest of the rules say.
function neverShare(text, words) {
  if (/[ऀ-ॿ]/.test(text)) return true; // Devanagari: not supported yet, fail closed
  if (DIGITS.test(text) || EMAIL.test(text)) return true;
  if (words.includes("at") && words.includes("dot") && words.some((w) => EMAIL_ENDINGS.has(w))) return true;
  let run = 0;
  for (const word of words) {
    run = SPOKEN_DIGITS.has(word) ? run + 1 : 0;
    if (run >= 4) return true;
  }
  if (words.some((w) => SINGLE_WORDS.has(w)) || NEVER_PHRASES.some((p) => contains(words, p))) return true;
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
  if (words.length > 1 && ACTION_VERBS.has(words[0]) && ACTION_OBJECTS.has(words[1])) return true;
  for (let index = 0; index < words.length; index += 1) {
    for (const lead of ACTION_LEADS) {
      const end = index + lead.length;
      if (startsWith(words, index, lead) && end < words.length && ACTION_VERBS.has(words[end])) return true;
    }
  }
  if (words.length && !words.some((w) => WH_WORDS.has(w))) {
    if (REPLY_LEADS.has(words[0])) return true;
    if (SOFT_REPLY_LEADS.has(words[0]) && words.length > 1 && (REPLY_LEADS.has(words[1]) || REPLY_FOLLOWERS.has(words[1]))) {
      return true;
    }
  }
  for (let index = 0; index + 2 < words.length; index += 1) {
    // "how many points do i have", not "do i have to pay for returns"
    if (startsWith(words, index, ["do", "i", "have"]) && (index + 3 >= words.length || words[index + 3] !== "to")) {
      return true;
    }
  }
  return false;
}

function isPersonal(text) {
  const words = wordsOf(text);
  if (neverShare(String(text === null || text === undefined ? "" : text), words) || describesCaller(words)) return true;
  const index = ownedRecordAt(words);
  if (index < 0) return false;
  for (const phrase of PROCEDURAL) {
    if (contains(words, phrase)) return false;
  }
  if (index > 0 && OWNER_PREPOSITIONS.has(words[index - 1])) {
    return isStateInterrogative(words);
  }
  return true;
}

function hasAntecedent(before) {
  return before.some((word) => !FUNCTION_WORDS.has(word) && !NON_REFERENTS.has(word));
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
    if (!hasAntecedent(words.slice(0, index))) return true;
  }
  return false;
}

function isContextDependent(text) {
  const words = wordsOf(text);
  if (!words.length) return false;
  if (CONNECTIVES.has(words[0])) return true;
  if (CONNECTIVE_PAIRS.has(words.slice(0, 2).join(" "))) return true;
  if (ELLIPSIS_LEADS.has(words[0]) && !words.slice(1).some((w) => CLAUSE_MARKERS.has(w))) {
    return true;
  }
  if (FOLLOW_UP_PHRASES.some((p) => contains(words, p)) || FOLLOW_UP_ENDINGS.has(words[words.length - 1])) {
    return true;
  }
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

// An answer that does not answer (a question back, "I'm not sure", a refusal) is spoken but never saved: cached, it becomes every later caller's answer, and it keeps rephrasings of the question from matching a real answer.
const NON_ANSWER_PHRASES = [
  "could you let me know",
  "could you tell me",
  "can you tell me",
  "could you clarify",
  "can you clarify",
  "could you specify",
  "can you specify",
  "could you provide",
  "can you provide",
  "please clarify",
  "please specify",
  "please provide",
  "let me know the ",
  "let me know which",
  "let me know what",
  "let me know your",
  "what do you mean",
  "which one do you mean",
  "i'm not sure",
  "i am not sure",
  "i don't know",
  "i do not know",
  "i can't help",
  "i cannot help",
  "i can't answer",
  "i cannot answer",
  "i'm unable",
  "i am unable",
  "i don't have access",
  "i do not have access",
  "i don't have information",
  "i do not have information",
  "need more information",
  "need more details",
];

function isNonAnswer(answer) {
  const text = String(answer || "").toLowerCase().replace(/\u2019/g, "'").split(/\s+/).filter(Boolean).join(" ");
  const sentences = (text.match(/[^.!?]+[.!?]*/g) || []).map((s) => s.trim()).filter((s) => s.replace(/[ .!?]/g, ""));
  if (!sentences.length) return false;
  if (sentences.every((s) => s.endsWith("?"))) return true;
  // Only when it leads: "Costs vary by destination. Please provide the address." still answers.
  return NON_ANSWER_PHRASES.some((phrase) => sentences[0].includes(phrase));
}

function leaks(shaped, values) {
  const flat = flatten(shaped);
  return Object.values(values).some((value) => value && flat.includes(flatten(value)));
}

module.exports = {
  // public
  isPersonal,
  isContextDependent,
  isNonAnswer,
  // used by conversation.js
  CONTEXT_BOUND_THRESHOLD,
  normalise,
  fill,
  abstract,
  leaks,
  slotNames,
};
