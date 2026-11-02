"use strict";

// What a chat turn tells and gives away: the names in it, the details the user told, its private
// words, and a reply masked before it is kept. Moved unchanged from session.js in v4 P3.

const { wordsOf, properNouns, tellsAboutCaller, instructs } = require("./wordRules/index.js");
const { NOT_GENERAL_TYPES } = require("./turnFrame.js");
const { FUNCTION, CALENDAR } = require("./frameWords.js");

// Phrases a name follows ("my name is sarah", "call me raj", "this is priya"). "I'm" is not one
// here: "I'm allergic" is a fact, not a name, and the shared question may carry it.
const NAME_LEADS = [["name", "is"], ["call", "me"], ["this", "is"]];
// "I'm Sarah" / "i am sarah, ...": the word after is a name when capitalised, or when the phrase ends with
// it; in a turn telling a fact only when "and" or a comma follows ("I'm diabetic." is the fact).
const SELF_INTRO = /\b[Ii](?:['\u2019]m| am|m)\s+(\p{L}+)(\s*(?:[,.!?;]|$)|\s+(?:and|from|here|calling|speaking)\b)?/gu;
// Words a person's name follows ("my colleague JOSE", "my son Arjun", "my teacher Mr Smith"): after
// my/our/his/her/their/your, the next capitalised word is a name whatever the model tagged it as.
const RELATIONS = new Set("colleague coworker friend son daughter wife husband partner mother mom mum father dad brother sister boss manager kid child baby grandma grandpa grandmother grandfather uncle aunt cousin neighbour neighbor roommate girlfriend boyfriend fiance fiancee teacher doctor client customer".split(" "));
const POSSESSIVE = new Set("my our his her their your s".split(" ")); // "s": "my wife's sister PRIYA"
const TITLES = new Set("mr mrs ms miss dr sir madam".split(" "));

// What names the caller in a turn: emails, long numbers, a name after "my name is", what the
// understanding model tagged as identifying, and, in a turn that is not telling a fact, any name it
// gives ("hi i'm sarah"). A fact turn keeps its words ("I'm allergic"): the question carries them.
function names(t, frame = null, fact = true) {
  const words = wordsOf(t);
  const found = new Set();
  const text = String(t || "");
  for (const named of [...(text.match(/\S+@\S+/g) || []), ...(text.match(/\p{Nd}(?:[\s-]?\p{Nd}){5,}/gu) || [])]) {
    for (const w of wordsOf(named)) found.add(w);
  }
  words.forEach((_, i) => {
    for (const lead of NAME_LEADS) {
      const end = i + lead.length;
      if (end < words.length && lead.every((w, k) => words[i + k] === w) && !FUNCTION.has(words[end])) found.add(words[end]);
    }
  });
  for (const x of frame ? frame.identifyingTexts : []) for (const w of wordsOf(x)) found.add(w);
  const tokens = text.match(/\p{L}+/gu) || [];
  for (let i = 1; i < tokens.length - 1; i++) {
    if (!RELATIONS.has(tokens[i].toLowerCase()) || !POSSESSIVE.has(tokens[i - 1].toLowerCase())) continue;
    const nxt = tokens[i + 1];
    // "Mr Smith", "O'Brien": the name is the word after the title or the one-letter part.
    const words = TITLES.has(nxt.toLowerCase()) || Array.from(nxt).length === 1 ? tokens.slice(i + 1, i + 3) : [nxt];
    for (const word of words) {
      const low = word.toLowerCase();
      if (word !== "I" && !FUNCTION.has(low) && !CALENDAR.has(low) && /[\p{Lu}\p{Lt}]/u.test(word)) found.add(low);
    }
  }
  for (const m of text.matchAll(SELF_INTRO)) {
    const word = m[1];
    const closer = m[2] === undefined ? null : m[2].trim();
    if (!FUNCTION.has(word.toLowerCase()) && (/^\p{Lu}/u.test(word) || (closer !== null && (!fact || closer === "," || closer === "and")))) {
      found.add(word.toLowerCase());
    }
  }
  return [...found].sort();
}

// A turn telling a fact, in two parts: what names the caller (never kept, never in a shared question)
// and the details a shared question must carry: a short number, a month or day, a place or thing the
// understanding model tagged ("3", "December", "Goa"). Any other capitalised word ("Priya") counts as
// a name, so a model that tags nothing keeps the chat private.
function told(t, frame) {
  const words = wordsOf(t);
  const named = new Set(names(t, frame));
  const tagged = new Set(frame.entities.filter((e) => !e.identifying && e.type !== "other_person").flatMap((e) => wordsOf(e.text)));
  const capitalised = new Set((String(t || "").match(/\p{L}+/gu) || [])
    .filter((w) => /^\p{Lu}/u.test(w) && w !== "I").map((w) => w.toLowerCase()).filter((w) => !FUNCTION.has(w)));
  const untagged = [...capitalised].filter((w) => !CALENDAR.has(w) && !tagged.has(w));
  for (const w of untagged) named.add(w);
  for (const w of words) if (/\p{Nd}/u.test(w) && w.length > 3) named.add(w);
  const details = new Set([...words.filter((w) => /\p{Nd}/u.test(w)), ...capitalised].filter((w) => !named.has(w)));
  for (const w of untagged) details.add(w);
  return [named, [...details].sort()];
}

// Everything in a turn that may identify the caller: its names, any number, any capitalised word.
// Broad on purpose; it only ever refuses a shared answer, so a wrong guess costs a hit.
function privateWords(t, frame = null) {
  const found = new Set([...wordsOf(t).filter((w) => /\p{Nd}/u.test(w)), ...properNouns(t), ...names(t, frame)]);
  return [...found].sort();
}
// A reply to a private turn is kept between turns only to follow the conversation: names, emails
// and numbers in it are masked first (any word with a capital, a digit, or a letter of a script
// without case).
const REPLY_WORD = /\S+@\S+|[\p{L}\p{N}_]+/gu;
const MASKED = /[\p{Lu}\p{Lt}\p{Lo}\p{N}]/u;
const masked = (reply) => String(reply ?? "").replace(REPLY_WORD, (w) => (w.includes("@") || MASKED.test(w) ? "_" : w));

// A stated turn as the voice classifier is sent it: masked as a reply is, and any word a private turn
// of the call held ("sharma") masked too.
const unnamed = (text, privateWords) =>
  masked(text).replace(/[\p{L}\p{N}_]+/gu, (w) => (privateWords.has(w.toLowerCase()) ? "_" : w));
// A first-person claim that something was done: a cached answer must never claim an action.

function norm(t) {
  return String(t || "").toLowerCase().replace(/^[\s\p{P}]+|[\s\p{P}]+$/gu, "").split(/\s+/).filter(Boolean).join(" ");
}

module.exports = {
  NAME_LEADS,
  SELF_INTRO,
  RELATIONS,
  POSSESSIVE,
  TITLES,
  names,
  told,
  privateWords,
  REPLY_WORD,
  MASKED,
  masked,
  unnamed,
  norm,
};
