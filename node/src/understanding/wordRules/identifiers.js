"use strict";

// Identifiers and declared values: whether an answer repeats a caller's ID, value or call context.

const {
  FUNCTION_WORDS,
  firstWords,
  flatten,
  hasPhrase,
  properNouns,
  wordsOf,
} = require("./text.js");
const {
  SPACED_DIGITS,
  STEERING,
} = require("./phrases.js");

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
function identifiers(texts) {
  const found = new Set();
  for (const text of texts) {
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
  const flat = flatten(answer);
  const tokens = new Set([...(String(answer || "").match(ID_TOKEN) || []).map(flatten), ...wordsOf(answer)]);
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
  leaks,
  ID_TOKEN,
  YEAR,
  identifiers,
  repeatsIdentifier,
  carriesCallContext,
  STEERING_BY_FIRST,
  NAMING,
  identifying,
};
