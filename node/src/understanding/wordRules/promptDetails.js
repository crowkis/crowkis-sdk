"use strict";

// System-prompt details: a caller's details a prompt gives, and answers that repeat them.

const {
  FUNCTION_WORDS,
  WORDS,
  isDecimalWord,
  numbersOf,
  startsUpper,
  wordsOf,
} = require("./text.js");
const {
  EMAIL_ENDINGS,
} = require("./phrases.js");

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
const EMAIL_ADDRESS = /[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+/g;
const LABEL = /^\s*([^:=\n]{1,40}?)\s*[:=]\s*(.*)$/;

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

module.exports = {
  PERSON_WORDS,
  RECORD_LABELS,
  BUSINESS_WORDS,
  LABEL_WORDS,
  SENTENCE_END,
  EMAIL_ADDRESS,
  LABEL,
  labelOf,
  aboutAPerson,
  valueWords,
  promptDetails,
  BASELINES,
  BASELINES_MAX,
  resetPromptBaselines,
  callerDetails,
  sameNumber,
  repeatsPromptDetails,
};
