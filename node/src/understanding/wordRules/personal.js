"use strict";
const {
  ACTION_VERBS,
  AUXILIARIES,
  CALLER_KINDS,
  CLAUSES,
  CLAUSE_MARKERS,
  DISCOURSE,
  FIRST_PERSON,
  FUNCTION_WORDS,
  GREETINGS,
  ID_WORDS,
  MATTERS,
  MONTHS,
  NUMBER_WORDS,
  ORDINALS,
  OWNED_THINGS,
  OWNERS,
  PERSONAL_MATTERS,
  PERSON_CUES,
  POSSESSIVES,
  QUESTION_LEADS,
  RELATIONS,
  REPLY_LEADS,
  REQUEST_VERBS,
  SENSITIVE,
  SINGLE_WORDS,
  SOFT_REPLY_LEADS,
  STATEMENT_SUBJECTS,
  STATE_WORDS,
  STREET_WORDS,
  TRIM_EDGES,
  UNIT_WORDS,
  WH_WORDS,
  amount,
  anyIn,
  capitalisedName,
  contains,
  firstWords,
  hasDigit,
  hasPhrase,
  properNouns,
  startsWith,
  unknown,
  wordsOf,
  ACTION_LEADS_BY_FIRST,
  CONNECTIVES,
  CRISIS_PHRASES,
  EMAIL_ENDINGS,
  SOMEONE,
  SPACED_DIGITS,
  THIRD_PERSON,
  flatten,
  STEERING,
} = require("./text.js");
const { urgent } = require("./urgent.js");

// Personal turns: the caller's own records, details, identity and sensitive matters.


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

const OWNER_PREPOSITIONS = new Set([
  "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
  "onto", "under", "via",
]);

const STATE_LEADS = new Set([
  "what", "whats", "when", "where", "which", "who", "how", "is", "are",
  "has", "have", "had", "did", "do", "does", "show", "tell", "check",
  "status",
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

const INTRO_AFTER_GREETING = [["i", "am"], ["i", "m"], ["this", "is"], ["it", "s"], ["my", "name"]];
// A verb first is a request only when it acts on something ("set a timer", "turn
// off the lights", "cancel my order"). A verb before a noun is search-style
// phrasing: "refund status for john", "return policy for shoes".
const ACTION_OBJECTS = new Set([
  ...FUNCTION_WORDS,
  "a", "an", "some", "another", "all", "everything", "up", "off", "out", "down", "over",
  "back", "away", "ahead", "his", "her", "our", "my", "me", "us",
]);
for (const subject of ["you", "i", "we", "they"]) ACTION_OBJECTS.delete(subject); // "do you ship abroad" asks, "do it" tells
const STATEMENT_VERBS = new Set(["is", "are", "was", "were", "s", "costs", "cost", "means", "includes", "has", "have"]);
// A recap of what the caller told this call: its answer holds what they said, so it is never a shared shape.
const RECAP = [
  ["so", "far"], ["know", "about", "me"], ["have", "on", "me"], ["have", "about", "me"],
  ["on", "file", "for", "me"], ["recap"],
];
const RECAP_BY_FIRST = firstWords(RECAP);

function asksRecap(text) {
  return hasPhrase(wordsOf(text), RECAP_BY_FIRST);
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
  ...RECAP,
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
const EMAIL = /[A-Za-z0-9._%+-]@[A-Za-z0-9-]/;
// An IPv4 address: personal data, as an IPv6 address already counts (its digit runs).
const URL_RE = /https?:\/\/|\bwww\./i; // a link can carry a token or an id
const IPV4 = /(?<![0-9.])(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])(?:\.(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])){3}(?![0-9]|\.[0-9])/;
const LETTER = /\p{L}/u;

// A turn longer than this is private without being read: every rule is linear in
// its length, and a caller's monologue is not a question other callers ask.
const MAX_TURN_CHARS = 1000;

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
const DATE = /(?<![0-9])[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}(?![0-9])/;
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
const ALNUM = /^[\p{L}\p{N}]$/u;

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
// What a person, not a product, does after an opening auxiliary: "does Mohit have".
const PERSON_VERBS = new Set([
  "have", "has", "had", "need", "want", "pick", "get", "come", "coming", "call", "called",
  "know", "live", "book", "booked", "order", "ordered", "pay", "paid", "arrive", "arrived",
  "still", "already", "sign", "signed", "speak", "talk", "collect", "collects", "visit", "attend",
]);
// "Can I speak to Meera", "pls connect to raghav sir": a person asked for by name.
const ASK_FOR = [
  ["speak", "to"], ["speak", "with"], ["talk", "to"], ["talk", "with"], ["connect", "to"],
  ["connect", "me", "to"], ["transfer", "to"], ["transfer", "me", "to"], ["ask", "for"],
  ["put", "me", "through", "to"],
];
const ASK_FOR_BY_FIRST = firstWords(ASK_FOR);
const POSSESSIVE_NAME = /(\p{L}+)['’]s\s+(\p{L}+)/gu;
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
      words.length > 1 && ACTION_VERBS.has(words[0]) && !words.some((w) => WH_WORDS.has(w)) &&
      (ACTION_OBJECTS.has(words[1]) || words.slice(1).some((w) => w === "my" || w === "our")) // "add milk to my list"
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
  if (DIGITS.test(text) || EMAIL.test(text) || IPV4.test(text) || URL_RE.test(text) || readsOutDigits(text, words)) return true;
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

// Identifiers and declared values: whether an answer repeats a caller's ID, value or call context.


function leaks(shaped, values) {
  const flat = flatten(shaped);
  return Object.values(values).some((value) => value && flat.includes(flatten(value)));
}

// A token that can identify someone: an order number, a PAN or IBAN, an email, an IP address.
const ID_TOKEN = /[A-Za-z0-9][A-Za-z0-9._@+-]*[A-Za-z0-9]/g;
const YEAR = /^(?:19|20)[0-9]{2}$/;

// The ID-like values said in `texts`, flattened as leaks() compares them: tokens with four
// or more digits (not a bare year) or an @, and digit groups said with spaces
// ("2345 6789 0123"). As in Python's _identifiers.
const SPOKEN_DIGIT_VALUES = { zero: "0", oh: "0", one: "1", two: "2", three: "3", four: "4", five: "5", six: "6", seven: "7", eight: "8", nine: "9" };
const SPOKEN_REPEATS = { double: 2, triple: 3 };
const SPOKEN_RUN_MIN = 4; // digits said as words that count as a number ("six seven zero eight")

// Digit strings said as words: "six seven zero double eight one" -> "670881".
function spokenNumbers(text) {
  const runs = [];
  let run = "";
  let times = 1;
  for (const word of [...wordsOf(text), ""]) {
    if (Object.hasOwn(SPOKEN_REPEATS, word)) times = SPOKEN_REPEATS[word];
    else if (Object.hasOwn(SPOKEN_DIGIT_VALUES, word)) { run += SPOKEN_DIGIT_VALUES[word].repeat(times); times = 1; }
    else {
      if (run.length >= SPOKEN_RUN_MIN) runs.push(run);
      run = "";
      times = 1;
    }
  }
  return runs;
}

function identifiers(texts) {
  const found = new Set();
  for (const text of texts) {
    for (const run of spokenNumbers(text || "")) found.add(run);
    for (const token of String(text || "").match(ID_TOKEN) || []) {
      const digits = (token.match(/[0-9]/g) || []).length;
      if (token.includes("@") || (digits >= 4 && !YEAR.test(token))) found.add(flatten(token));
    }
    for (const group of String(text || "").match(SPACED_DIGITS) || []) {
      const joined = group.replace(/[^0-9]/g, "");
      if (joined.length >= 5) found.add(joined);
    }
  }
  return new Set([...found].filter((value) => value.length >= 4));
}

// Whether `answer` says one of `ids`. A short value must be a whole token of the answer
// ("1800" is not in "21,800"); a long one may appear anywhere in it. As in Python.
function repeatsIdentifier(answer, ids) {
  const spoken = spokenNumbers(answer || "");
  const flat = flatten(answer) + spoken.join("|"); // digits said as words
  const tokens = new Set([...(String(answer || "").match(ID_TOKEN) || []).map(flatten), ...wordsOf(answer), ...spoken]);
  for (const token of [...tokens]) tokens.add(bare(token)); // "Rahulji" says Rahul
  return [...ids].some((value) => (value.length >= 6 ? flat.includes(value) : tokens.has(value)));
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

// How the caller gives a name. Case does not matter (speech-to-text often lower-cases names): over-capturing
// only keeps answers that say the captured word private. Not a name: an article or other function word,
// a word ending in -ing, or one of these common words after a lead. As in Python.
// Phrases after which the caller gives a name: "my name is sarah", "mera naam hai raj", "this is raj".
const NAMING = [["name", "is"], ["name", "s"], ["call", "me"], ["naam", "hai"], ["naam"], ["this", "is"], ["i", "m"], ["i", "am"],
  ["myself"], ["speaking", "with"]];
// Leads that need a capital in Chat (voice takes lower case too), as a plain word can follow them ("I'm diabetic").
const NAMING_WEAK = [["this", "is"], ["i", "m"], ["i", "am"], ["myself"], ["speaking", "with"], ["it", "s"], ["it", "is"], ["its"]].map((l) => l.join(" "));
// Leads only at the start of the turn (after a greeting): "it's Rahul", but not "I think it is open".
const NAMING_AT_START = [["it", "s"], ["it", "is"], ["its"]];
const NAME_LEADS_BY_FIRST = firstWords([...NAMING, ...NAMING_AT_START]);
// A name said first: "Rahul here", "Rahul this side", "Rahul speaking", at the start of the turn only.
const NAME_TRAILERS = [["here"], ["this", "side"], ["speaking"]];
const NAME_PARTS = 3;
const NAME_MIN_LENGTH = 2;
const NOT_NAMES = new Set([
  "not", "here", "new", "interested", "from", "about", "urgent", "regarding", "sorry", "sure", "fine", "good",
  "ok", "okay", "ready", "back", "also", "just", "still", "very", "so", "too", "available", "unable", "unsure",
  "happy", "glad", "wondering", "afraid", "writing", "important", "serious", "emergency", "wrong", "right",
  "hai", "hain", "hoon", "hu", // Hinglish "mera naam Rahul hai"
  "tomorrow", "today", "tonight", "later", "soon", "now", "again", "open", "free", "closed", "possible", // "call me tomorrow", "it's free"
  "correct", "true", "late", "early", "easy", "cheap", "time",
]);
const HONORIFIC = /(?:ji|jee)$/;

// A name without the Hindi honorific glued on ("rahulji" -> "rahul").
function bare(word) {
  const stripped = word.replace(HONORIFIC, "");
  return stripped.length >= NAME_MIN_LENGTH ? stripped : word;
}

// The leading words of `tokens` that read as a name; `strict` wants a capital first letter.
function nameWords(tokens, strict) {
  const out = [];
  for (const token of tokens.slice(0, NAME_PARTS)) {
    const word = token.toLowerCase();
    if ((strict && token[0] === token[0].toLowerCase()) || FUNCTION_WORDS.has(word) || GREETINGS.has(word) || NOT_NAMES.has(word) || word.endsWith("ing")) break;
    out.push(word);
  }
  return out;
}

// The names callers gave in `texts` ("my name is Rahul Verma", "this is harpreet iyer calling", "mera naam
// Rahul hai", "Rahul here"): each word of the name, lower-cased and flattened as leaks compares.
// After a weak lead ("I'm", "this is") a lower-case word is a name only with `lowercase` (voice); Chat reads names
// into its question rules too, so there "I'm diabetic" must not make "diabetic" a name.
function statedNames(texts, lowercase = true) {
  const found = new Set();
  for (const text of texts) {
    const tokens = String(text || "").match(/[\p{L}\p{M}\p{N}]+/gu) || [];
    const words = tokens.map((t) => t.toLowerCase());
    let start = 0;
    while (start < words.length && GREETINGS.has(words[start])) start += 1;
    for (let at = 0; at < words.length; at++) {
      for (const lead of NAME_LEADS_BY_FIRST.get(words[at]) || []) {
        if (!lead.every((w, i) => words[at + i] === w)) continue;
        if (NAMING_AT_START.includes(lead) && at !== start) continue;
        for (const w of nameWords(tokens.slice(at + lead.length), !lowercase && NAMING_WEAK.includes(lead.join(" ")))) found.add(w);
      }
    }
    for (const trailer of NAME_TRAILERS) {
      for (let size = 1; size <= NAME_PARTS; size++) {
        const end = start + size;
        if (trailer.every((w, i) => words[end + i] === w) && nameWords(tokens.slice(start, end), !lowercase).length === size) {
          for (const w of words.slice(start, end)) found.add(w);
        }
      }
    }
  }
  return new Set([...found].filter((value) => value.length >= NAME_MIN_LENGTH));
}

const STEERING_BY_FIRST = firstWords(STEERING);

// A system prompt can carry one caller's details ("The caller is Asha Rao, account
// 99812"). An answer that repeats them must never be shared. Same rules as Python
// (voice.py, _caller_details); fixtures/prompt-guard-cases.json checks both.
//
// 1. Across calls (the reliable one): a bot's own instructions are the same on every
//    call, so once an agent has been seen with two different system prompts, every word
//    and number of this call's prompt not in all of them is a caller detail.
// 2. Before that: the sentences of the prompt that are about a person.

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

module.exports = {
  asksRecap,
  PROCEDURAL,
  PROCEDURAL_BY_FIRST,
  MAIN_THINGS,
  OWNER_PREPOSITIONS,
  STATE_LEADS,
  CALLER_LEADS,
  SELF_PHRASES,
  SELF_PHRASES_BY_FIRST,
  describesCaller,
  ownedRecordAt,
  procedural,
  requests,
  isStateInterrogative,
  INTRO_AFTER_GREETING,
  ACTION_OBJECTS,
  STATEMENT_VERBS,
  NEVER_PHRASES,
  NEVER_PHRASES_BY_FIRST,
  STORY_PHRASES,
  STORY_PHRASES_BY_FIRST,
  PAST_TENSE,
  NOT_A_STORY,
  STORY_FILLERS,
  DIGITS,
  EMAIL,
  IPV4,
  LETTER,
  MAX_TURN_CHARS,
  DISCLOSURE_LEADS,
  DISCLOSURE_LEADS_BY_FIRST,
  STATES,
  SELF_MARKERS,
  KINDS_OF_PEOPLE,
  DATE,
  HASH_NUMBER,
  CODE,
  QUANTITIES,
  BARE_NUMBER,
  ENDS_IN,
  ALNUM,
  isStreetWord,
  isNumberNear,
  isNumberWord,
  identifies,
  INTRO_LEADS,
  INTRODUCTIONS,
  INTRODUCTIONS_BY_FIRST,
  NAME_ARTICLES,
  CLAUSE_OPENERS,
  PERSON_VERBS,
  ASK_FOR,
  ASK_FOR_BY_FIRST,
  POSSESSIVE_NAME,
  namesSomeone,
  discloses,
  carriesDetail,
  tooLong,
  unreadable,
  readsOutDigits,
  commands,
  asserts,
  tellsOwnStory,
  neverShare,
  DIAGNOSIS_LEADS,
  DIAGNOSIS_LEADS_BY_FIRST,
  ARTICLES,
  HAVE_OBJECTS,
  diagnosis,
  sensitiveSelf,
  ASKING_WORDS,
  ASKING_LEADS,
  FIRST_CLAUSE,
  NEUTRAL,
  asks,
  isPersonal,
  lookupOnly,
  leaks,
  ID_TOKEN,
  statedNames,
  bare,
  YEAR,
  identifiers,
  repeatsIdentifier,
  carriesCallContext,
  STEERING_BY_FIRST,
  NAMING,
  identifying,
};
