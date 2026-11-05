"use strict";
const { NOT_GENERAL_TYPES } = require("../model/frame.js");
const { tellsAboutCaller, instructs } = require("./callContext.js");
const { wordsOf, properNouns } = require("./text.js");

// The word checks Chat's frame rules use: tokens and stems, words any question may add, and the
// patterns of an identifying detail. Moved unchanged from verify.js in v4 P3.

// Words any question may use without them appearing in the turn: grammar, question words and
// ordinary request verbs. Never decides kind or privacy.
const FUNCTION = new Set(`a an the and or but if of to in on at for from by with about into over under after before
during than then so as is are was were be been being am do does did done doing have has had having can could will
would shall should may might must i you we they it its this that these those there here what which who whom whose
when where why how much many long often any some each every all no not yes my your our their me us them per same
other another own just only also more most less least very please get got getting give make take need want use used
using apply applying offer offers offered available availability allowed allow include includes included work works
working cost costs charge charged charges price pricing fee fees option options way ways happen happens like
differ different one two three four five six seven eight nine ten first second third time times day days
tell find found look looking show give know serve serves served recommend suggest
someone somebody anyone person people year years old aged`.split(/\s+/));

const NUMWORDS = { one: "1", two: "2", three: "3", four: "4", five: "5", six: "6", seven: "7", eight: "8", nine: "9", ten: "10" };
const UNITS = /^\s*(rupees?|rs|inr|dollars?|usd|items?|people|persons?|days?|weeks?|months?|years?|hours?|kg|gb|inch(es)?|%)/;
const EMAIL = /\S+@\S+|\bat\s+(gmail|yahoo|hotmail|outlook)\b/i;
const PHONE = /\b\d{10}\b|\(\d{3}\)\s*\d{3}-\d{4}/;

function toks(t) {
  return (String(t || "").toLowerCase().match(/[a-z0-9]+/g) || []).map((w) => NUMWORDS[w] || w);
}

/** Crude, symmetric word-form normaliser: expires/expire, removing/remove, qualifies/qualify. */
function stem(w) {
  for (const suffix of ["ing", "ed", "es", "s"]) {
    if (w.length > 4 && w.endsWith(suffix)) { w = w.slice(0, -suffix.length); break; }
  }
  if (w.length > 6 && w.endsWith("ic")) w = w.slice(0, -2); // allergic/allergy, diabetic/diabetes; not topic, music
  if (w.length > 3 && w.endsWith("e")) w = w.slice(0, -1);
  if (w.length > 3 && (w.endsWith("y") || w.endsWith("i"))) w = w.slice(0, -1);
  return w;
}

// Neutral words a stand-alone rewrite may add although the user did not say them ("how many people live
// there" -> "population"). Exact words, never stems ("tim" is not "time"), and none that could change
// what is asked ("avoid", "best", "cheapest", "safe") or tailor it ("vegan", "child").
const QUESTION_WORDS = new Set("population distance duration step steps process amount number list requirements difference differences type types kind kinds".split(" "));
const REFERRING = new Set("it its they them their there here this that those these he she him his her".split(" "));
const CONTRACTION = new Set("s t d m re ll ve".split(" ")); // "what's" -> "what", "s": "s" names nothing
const CLAUSE_START = new Set("i we you he she they it my our your his her their me".split(" "));
// Acronyms of things, never of a person ("SIM porting", "a UPI refund"): an all-caps word in a shared
// question that is one of these is no name (v4, misfire B05). "Ram" or "Sim" written as a name is.
const COMMON_ACRONYMS = new Set([
  "sim", "esim", "upi", "otp", "pin", "emi", "kyc", "gst", "atm", "usb", "api", "faq", "pdf", "sms", "mms", "gdpr",
  "icu", "opd", "ac", "tv", "wifi", "gps", "id", "sso", "csv", "vpn", "url", "ssd", "ram", "cpu", "nfc", "qr",
  "pnr", "ifsc", "neft", "rtgs", "imps", "cod", "eta", "ev", "abs",
]);
// Words that name a kind of fact, not which one: "allergies" alone does not carry "allergic to
// penicillin". A heuristic list; a fact made only of them ("I'm allergic.") still counts them.
const GENERIC_FACT = new Set("allergy allergic allergies intolerant intolerance sensitive sensitivity condition disease illness problem issue".split(" ").map(stem));

function looksIdentifying(question) {
  if (EMAIL.test(question) || PHONE.test(question)) return true;
  const low = question.toLowerCase();
  const re = /\d(?:[\s-]?\d){4,}/g;
  let m;
  while ((m = re.exec(low)) !== null) {
    if (!UNITS.test(low.slice(m.index + m[0].length, m.index + m[0].length + 12))) return true;
  }
  return false;
}

const DAYS = "monday tuesday wednesday thursday friday saturday sunday".split(" ");
const CALENDAR = new Set([..."january february march april may june july august september october november december".split(" "),
  ...DAYS, ...DAYS.map((d) => d + "s")]);

// Facts that tailor an answer to the caller: what they have. What the user told (a place, a time, a
// number) is in `stated`, from fixed code; a place or time in an earlier shared question is only its topic.
const TOLD_TYPES = new Set(["condition"]);

// Patterns Chat's save rules look for in an answer: an email, a long digit run (an ID, an account),
// a claim that something was done. Moved unchanged from session.js in v4 P3.

const ANSWER_EMAIL = /\S+@\S+/;
const ANSWER_LONG_DIGITS = /\d(?:[\s-]?\d){5,}/;
const ACTION_CLAIM = new RegExp(
  "\\b(i\\s*(have|['’]ve)|i\\s+just|we\\s*(have|['’]ve))\\s+(cancel+ed|booked|refunded|processed|changed|updated|" +
  "reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\\b" +
  "|\\bi(\\s+will|['’]ll)\\s+(add|cancel|book|send|schedule|reserve|place|remind|order)\\b" +
  "|\\b(has|have)\\s+been\\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted|added)\\b", "i");

// What a chat turn tells and gives away: the names in it, the details the user told, its private
// words, and a reply masked before it is kept. Moved unchanged from session.js in v4 P3.


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
  COMMON_ACRONYMS,
  TOLD_TYPES,
  CALENDAR,
  DAYS,
  FUNCTION,
  NUMWORDS,
  UNITS,
  EMAIL,
  PHONE,
  toks,
  stem,
  QUESTION_WORDS,
  REFERRING,
  CONTRACTION,
  CLAUSE_START,
  GENERIC_FACT,
  looksIdentifying,
  ACTION_CLAIM,
  ANSWER_EMAIL,
  ANSWER_LONG_DIGITS,
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
