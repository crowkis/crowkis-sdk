"use strict";

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

function speakable(text) {
  return !UNSPEAKABLE.test(text || "");
}

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

function describesCaller(words) {
  if (SELF_PHRASES.some((phrase) => contains(words, phrase))) return true;
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
// Phrases after which the caller gives a name: "my name is sarah", "this is raj".
const NAMING = [["name", "is"], ["call", "me"], ["this", "is"], ["i", "m"], ["i", "am"]];

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
  if (STEERING.some((phrase) => contains(words, phrase))) {
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

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
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
    this.serveAbove = serveAbove;
    this.minWords = minWords;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.commitments = commitments;
    this.shortTurns = Boolean(shortTurns);
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
    this.notShareable = 0;
    this.heldCommitments = 0;
    this.unspeakable = 0;
    // The question the latest stored answer was stored under.
    this._lastStored = null;
    this._fillers = new Map();
    this._open = false;
    this._cancelled = false;
    this._turnMark = 0;
    this._cacheable = false;
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
    const decision = await this._decide(callerSaid);
    this._cacheable = false;
    if (decision.needsModel) {
      [decision.messages, decision.cacheable] = this._modelMessages(callerSaid);
      this._cacheable = decision.cacheable;
    }
    return decision;
  }

  // What the model should read to answer this turn, and whether that answer may
  // be cached. A shared answer is only safe when the model saw nothing but the
  // cache key: the question, and for a follow-up the question before it.
  // Personal turns get the whole call and are never shared.
  _modelMessages(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (text.split(/\s+/).filter(Boolean).length < this.minWords || isPersonal(text)) return [null, false];
    if (!isContextDependent(text)) return [[{ role: "user", content: callerSaid }], true];
    const prior = this._priorUser();
    if (prior === null || isPersonal(prior)) return [null, false];
    return [[{ role: "user", content: prior }, { role: "user", content: callerSaid }], true];
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
      return new TurnDecision("filler", {
        text: filler,
        audio: await this._voiced(filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
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

    const held = this._held(hit, answer, short);
    if (held) {
      this.inferred += 1;
      return new TurnDecision("infer", { confidence: hit.confidence, reason: held });
    }

    this.served += 1;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: answer });
    return new TurnDecision("serve", {
      text: answer,
      audio: await this._voiced(answer, { cacheable: !personal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
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
  // text to speak, from the cache or from the model.
  async answer(callerSaid, llm, { system = null } = {}) {
    const decision = await this.decide(callerSaid);
    if (!decision.needsModel) return decision;
    let messages = decision.messages || [...this.injections(), { role: "user", content: callerSaid }];
    if (system) messages = [{ role: "system", content: system }, ...messages];
    decision.text = await llm(messages);
    await this._recordModelTurn(callerSaid, decision.text);
    return decision;
  }

  // Keep a turn in this call's transcript and never cache it. For a model that
  // holds the whole conversation itself (a realtime speech model): it cannot be
  // given decision.messages, so nothing it says is shared.
  recordPrivateTurn(callerSaid, modelSaid) {
    if (this._cancelled) return;
    this._open = false;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (this._cacheable) this.notShareable += 1;
    this._cacheable = false;
  }

  // Record the model's answer to the turn decide() last handled, and cache it if
  // allowed. Only an answer written from decision.messages reaches this, so it is
  // shared exactly when decide() said it may be. Never rejects: a refused write
  // (security pipeline, rate limit, cache down) must not end a call.
  //
  // Resolves to what happened to the answer: "saved" (shared), "template" (shared
  // as a shape, this caller's values removed), "kept" (the model read the whole
  // call, so it stays in this call), "private" (personal, or repeats this caller's
  // details), "non_answer", "not_saved" (a follow-up with nothing to key it to),
  // "refused" (the write failed) or "interrupted".
  async _recordModelTurn(callerSaid, modelSaid) {
    if (this._cancelled) return "interrupted";
    this._open = false;
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    const keyed = this._contextKey(callerSaid, text);
    const cacheable = this._cacheable;
    this._cacheable = false;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (!(typeof modelSaid === "string" && modelSaid.trim())) return "non_answer";
    if (keyed === null) return "not_saved";
    try {
      if (isPersonal(text)) {
        return (await this._learnPersonal(keyed, modelSaid)) ? "template" : "private";
      }
      if (!cacheable) {
        this.notShareable += 1;
        return "kept";
      }
      if (leaks(modelSaid, this.values)) {
        this.notShareable += 1;
        return "private";
      }
      await this.agent.learn(keyed, modelSaid, { ttl: this.ttl });
      this._lastStored = keyed;
      return "saved";
    } catch (error) {
      this.learnErrors += 1;
      return "refused";
    }
  }

  injections() {
    return this.transcript.slice();
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
      notShareable: this.notShareable,
      commitmentsSentToModel: this.heldCommitments,
      unspeakableAnswers: this.unspeakable,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
    };
  }

  _hasValues() {
    return Object.keys(this.values).length > 0;
  }

  _priorUser() {
    for (let index = this.transcript.length - 1; index >= 0; index -= 1) {
      if (this.transcript[index].role === "user") return this.transcript[index].content;
    }
    return null;
  }

  _contextKey(callerSaid, text) {
    if (!isContextDependent(text)) return callerSaid;
    const prior = this._priorUser();
    if (prior === null || prior === undefined) return null;
    return `${prior} || ${callerSaid}`;
  }

  // Store a personal answer as a shape. False when it cannot be made generic.
  async _learnPersonal(keyed, modelSaid) {
    const shaped = abstract(modelSaid, this.values);
    if (this._hasValues() && slotNames(shaped).length && !leaks(shaped, this.values)) {
      await this.agent.learn(keyed, shaped, { ttl: this.ttl, template: true });
      return true;
    }
    this.uncacheablePersonal += 1;
    return false;
  }

  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    if (!cacheable) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
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
      session._cacheable = session._modelMessages(callerSaid)[1] && !carriesCallContext(agentSaid, keyed, earlier);
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

module.exports = {
  VoiceSession,
  TurnDecision,
  warmFromCalls,
  _speakable: speakable,
  _isPersonal: isPersonal,
  _isContextDependent: isContextDependent,
  _abstract: abstract,
  _fill: fill,
};
