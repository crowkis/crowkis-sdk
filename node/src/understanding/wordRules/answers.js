"use strict";
const {
  contentWords,
  escapeRegExp,
  FUNCTION_WORDS,
  WORDS,
  isDecimalWord,
  numbersOf,
  startsUpper,
  wordsOf,
  EMAIL_ENDINGS,
} = require("./text.js");

// Answers: spoken or screen text, non-answers, answer shapes, questions about other things.


const SLOT = /\{([^{}\s]+)\}/g;

// Text written for a screen: a link, code, or markup a voice would read out.
const UNSPEAKABLE = /https?:\/\/|www\.|`|\]\(|\*\*|^\s*(?:#{1,6}\s|\|)/im;

function speakable(text) {
  return !UNSPEAKABLE.test(text || "");
}

// Two questions about different things: each has content words the other does not ("on
// Saturday" / "on Sunday"). A rewording only adds or drops words on one side, or changes
// how it asks ("can I" / "do I"). Same as Python's _different_specifics.
function differentSpecifics(asked, stored) {
  const a = contentWords(asked);
  const s = contentWords(stored);
  return [...a].some((w) => !s.has(w)) && [...s].some((w) => !a.has(w));
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
  "i do not have information", "i don't have that information", "i do not have that information", "i don't have the information", "i do not have the information", "i don't have any information", "i do not have any information", "i need to know", "please let me know", "need more information", "need more details",
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

// System-prompt details: a caller's details a prompt gives, and answers that repeat them.


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
  SLOT,
  UNSPEAKABLE,
  speakable,
  differentSpecifics,
  slotNames,
  fill,
  MIN_ABSTRACT_LEN,
  abstract,
  NON_ANSWER_PHRASES,
  REDIRECTS,
  SOFTENERS,
  SENTENCE,
  isNonAnswer,
  answersAfterBut,
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
