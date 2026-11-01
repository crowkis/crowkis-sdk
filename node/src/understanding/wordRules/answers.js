"use strict";

// Answers: spoken or screen text, non-answers, answer shapes, questions about other things.

const {
  contentWords,
  escapeRegExp,
} = require("./text.js");

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
};
