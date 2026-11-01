"use strict";

// Follow-ups and cut-offs: turns that lean on an earlier one, or stop mid-question.

const {
  BARE,
  CLAUSE_MARKERS,
  FRAMING_WORDS,
  FUNCTION_WORDS,
  NON_REFERENTS,
  PRONOUN_FOLLOWERS,
  ROLES,
  firstWords,
  hasPhrase,
  stem,
  splitPlain,
  wordsOf,
} = require("./text.js");
const {
  CONNECTIVES,
  FOLLOW_UP_WORDS,
} = require("./phrases.js");
const {
  asks,
  isPersonal,
  lookupOnly,
  tooLong,
} = require("./personal.js");

const CONNECTIVE_PAIRS = new Set(["what about", "how about", "ok and", "okay and"]);

const ELLIPSIS_LEADS = new Set([
  "for", "with", "about", "in", "on", "at", "to", "from", "by",
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

function hasAntecedent(before) {
  return before.some((word) => !FUNCTION_WORDS.has(word) && !NON_REFERENTS.has(word));
}

// "the doctor" after nothing is someone from an earlier turn, like "he".
const THE_ROLES = new Set(["doctor", "nurse", "dentist", "surgeon", "specialist", "teacher", "professor", "lawyer", "therapist", ...ROLES]);

// A word that opens a new clause: only what came before it can be a pronoun's antecedent.
const CLAUSE_JOINERS = new Set([
  "and", "but", "so", "or", "then", "because", "if", "when", "while", "since", "unless", "whether",
  "that", "after", "before", "once", "although",
]);

const PERSON_PRONOUNS = new Set(["he", "she", "him", "her", "his", "hers"]);

// "fast for it": an "it" after a preposition points at an earlier topic; "return it" stays as it was.
const PREPOSITIONS = new Set(["for", "about", "on", "with", "of", "from", "to"]);

// Words in the question's own frame ("what days does ...") are not what a pronoun points at.
function hasClauseAntecedent(before) {
  let last = -1;
  before.forEach((word, i) => { if (CLAUSE_JOINERS.has(word)) last = i; });
  return last >= 0 && hasAntecedent(before.slice(0, last));
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
    if ((PERSON_PRONOUNS.has(word) || (word === "it" && index && PREPOSITIONS.has(words[index - 1]))) && !hasClauseAntecedent(words.slice(0, index))) return true;
  }
  for (let index = 1; index < words.length; index += 1) {
    if (THE_ROLES.has(words[index]) && words[index - 1] === "the" && !hasClauseAntecedent(words.slice(0, index - 1))) return true;
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

function root(word) {
  const r = stem(word);
  return r.length > 3 && r[r.length - 1] === r[r.length - 2] ? r.slice(0, -1) : r; // "cancelling" -> "cancel"
}

// A short question whose only topic is an "-ing" form of what the previous caller turn said ("How
// long does porting take?" after "...to port my number..."): on a telecom call it means number
// porting, alone it means software. Same-form repeats and longer questions stand alone.
// shortcut: -ing forms only, one earlier turn; upgrade with the pluggable understander.
function leansOn(text, previous) {
  const words = wordsOf(text);
  const before = wordsOf(previous);
  if (!before.length || words.length > FOLLOW_UP_WORDS) return false;
  const roots = new Set(before.map(root));
  const shared = new Set(words.filter((w) => !FUNCTION_WORDS.has(w) && !FRAMING_WORDS.has(w) && !NON_REFERENTS.has(w) && roots.has(root(w))).map(root));
  return shared.size === 1 && words.some((w) => w.endsWith("ing") && shared.has(root(w)) && !before.includes(w));
}

// A chain is private when any turn of it is, or when its root ("Priya Sharma.",
// "Bipolar.") is too short to stand alone or neither asks nor requests anything.
function privateChain(chain, minWords = 0) {
  const root = chain.length ? String(chain[0] || "").trim() : "";
  if (chain.length && (root.split(/\s+/).filter(Boolean).length < minWords || !asks(root))) return true;
  return chain.some((turn) => isPersonal(turn) || lookupOnly(turn));
}

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

module.exports = {
  CONNECTIVE_PAIRS,
  ELLIPSIS_LEADS,
  FOLLOW_UP_PHRASES,
  FOLLOW_UP_PHRASES_BY_FIRST,
  FOLLOW_UP_ENDINGS,
  ANAPHOR_PHRASES,
  ANAPHORS,
  DEMONSTRATIVES,
  hasAntecedent,
  leansOn,
  pointsForward,
  hasBareAnaphor,
  isContextDependent,
  privateChain,
  DANGLING,
  TRAILING_FILLERS,
  TAKES_IN_ON,
  unfinished,
};
