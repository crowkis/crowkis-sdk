"use strict";

// Word and phrase tables more than one theme of the word rules reads.

const {
  MATTERS,
  RELATIONS,
  firstWords,
} = require("./text.js");

const CONTEXT_BOUND_THRESHOLD = 0.995;

// How a cached answer that commits the business (a price, a refund, a policy)
// may be spoken. Only matters when the server's decision engine flags one.
const COMMITMENTS = {
  serve: () => true,
  exact: (hit) => Boolean(hit.exact),
  never: () => false,
};

const CONNECTIVES = new Set(["and", "so", "but", "or", "also", "then", "aur", "phir", "lekin", "toh"]);

// Which question a shared answer was saved for, kept beside it as a plain key (keyed by the
// answer, per tenant), so a hit can be checked against the question it really answers. A
// plain GET/SET key, not the tool cache: that is an Enterprise feature.
const QUESTIONS_KEPT = 8;
// How long a question record lives when the answer has no TTL of its own.
const QUESTION_TTL = 30 * 24 * 3600;

const EMAIL_ENDINGS = new Set(["com", "in", "org", "net", "co", "io"]);
// After these leads, an action verb is a request for the agent to do something.
const ACTION_LEADS = [
  ["please"], ["can", "you"], ["could", "you"], ["will", "you"], ["would", "you"],
  ["i", "want", "to"], ["i", "d", "like", "to"], ["i", "would", "like", "to"],
  ["i", "need", "to"], ["let", "me"], ["i", "wanna"],
];
const ACTION_LEADS_BY_FIRST = firstWords(ACTION_LEADS);
// A crisis, said in words: private, and what follows it stays with it.
const CRISIS_PHRASES = [
  ["end", "it", "all"], ["kill", "myself"], ["hurt", "myself"], ["harm", "myself"],
  ["want", "to", "die"], ["self", "harm"], ["end", "my", "life"], ["take", "my", "life"],
  ["reason", "to", "live"], ["better", "off", "dead"], ["not", "breathing"], ["heart", "attack"],
  ["ending", "my", "life"], ["ending", "it", "all"], ["end", "myself"], ["kill", "me"],
  ["panic", "attack"], ["wanna", "die"],
];
// Digits read out in groups: "4 4 0 9", "98 765 43". Commas and points are left
// out, so a price ("1,499") or a weight ("1.5") is not an identifier.
const SPACED_DIGITS = /[0-9]+(?:[ \t-]+[0-9]+)+/g;
const THIRD_PERSON = new Set(["he", "she", "him", "her", "his", "hers", "their", "theirs"]);
// One named person the caller speaks about ("wife has diabetes", "she is pregnant"),
// not a kind of person ("a family lawyer").
const SOMEONE = new Set([...RELATIONS, ...THIRD_PERSON]);
for (const kind of [
  "family", "friend", "partner", "children", "kids", "kid", "child", "parent", "parents", "baby",
  "neighbour", "neighbor", "cousin", "their", "theirs",
]) SOMEONE.delete(kind);
// A follow-up this short, after an emergency or a medical turn, is about it.
const FOLLOW_UP_WORDS = 8;
const URGENT = new Set([
  ...MATTERS,
  "suicide", "suicidal", "overdose", "overdosed", "unconscious", "collapsed", "bleeding",
  "choking", "fainted", "swallowed", "seizure", "drowning", "poisoned", "ambulance",
  "breathing", "fire", "emergency", "cpr",
]);

// What the server puts in a stored answer in place of a caller's detail (its PII scrubber):
// "pii_email_k3fa9". Spoken, it is noise at best. As in Python.
const PII_PLACEHOLDER = /(?<![A-Za-z0-9_])pii_(?:email|phone|natid|card|person|location|ip|dob|passport|iban)_[A-Za-z0-9]+/i;

// A caller turn that tries to change what the model says for the rest of the call.
const STEERING = [
  ["pretend"], ["from", "now", "on"], ["for", "this", "call"], ["for", "the", "rest"],
  ["ignore"], ["forget"], ["act", "as"], ["you", "are", "now"], ["assume"],
  ["always", "say"], ["tell", "everyone"], ["roleplay"], ["role", "play"],
];

module.exports = {
  CONTEXT_BOUND_THRESHOLD,
  COMMITMENTS,
  CONNECTIVES,
  QUESTIONS_KEPT,
  QUESTION_TTL,
  EMAIL_ENDINGS,
  ACTION_LEADS,
  ACTION_LEADS_BY_FIRST,
  CRISIS_PHRASES,
  SPACED_DIGITS,
  THIRD_PERSON,
  SOMEONE,
  FOLLOW_UP_WORDS,
  URGENT,
  PII_PLACEHOLDER,
  STEERING,
};
