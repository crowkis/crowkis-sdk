"use strict";

// Crisis and urgent turns: self-harm, poisoning, injury, collapse, assault.

const { RELATIONS, firstWords, hasPhrase, stem, CRISIS_PHRASES } = require("./text.js");

const CRISIS_PHRASES_BY_FIRST = firstWords(CRISIS_PHRASES);

// An emergency or a crisis, in the languages callers use (English, Hindi/Hinglish,
// Spanish, Portuguese, French), found by its shape rather than by fixed sentences.
// Word starts that are always one: "suicidal", "overdosed", "behosh", "desmayó".
const EMERGENCY_STEMS = [
  "suicid", "overdos", "sobredos", "envenen", "behosh", "unconscious", "inconscien", "desmay",
  "desmai", "évanoui", "evanoui", "fainted", "collapsed", "convuls", "seizure", "choking",
  "atragant", "engasg", "étouff", "drowning", "ahogand", "afogand", "bleeding", "sangrand",
  "khudkushi", "aatmahatya", "atmahatya", "infarto", "poisoned", "poisoning", "electrocut",
];
const EMERGENCY_PHRASES = [
  ["heart", "attack"], ["not", "breathing"], ["no", "respira"], ["não", "respira"], ["nao", "respira"],
  ["ne", "respire"], ["saans", "nahi"], ["saans", "nahin"], ["dil", "ka", "daura"], ["crise", "cardiaque"],
  ["chest", "pain"], ["dolor", "de", "pecho"], ["dor", "no", "peito"], ["seene", "mein", "dard"],
  ["cut", "myself"], ["cutting", "myself"], ["hurt", "myself"], ["hurting", "myself"],
  ["harm", "myself"], ["harming", "myself"], ["burn", "myself"], ["burned", "myself"],
  ["me", "corté"], ["me", "corte"], ["me", "corto"], ["me", "cortei"], ["me", "cortar"],
  ["me", "matar"], ["me", "mato"], ["me", "tuer"], ["me", "couper"], ["khud", "ko"],
  ["cortarme"], ["matarme"], ["lastimarme"], ["suicidarme"], ["having", "a", "stroke"],
  ["had", "a", "stroke"], ["khoon", "nikal"],
];
const EMERGENCY_PHRASES_BY_FIRST = firstWords(EMERGENCY_PHRASES);
// A wish to die ("i want to die", "quiero morir", "marna chahta hoon"), or not to
// live ("i don't want to live anymore", "jeena nahi chahta"), in any word order.
const WANTS = new Set(["want", "wanna", "going", "gonna", "quiero", "quero", "veux", "voudrais", "chahta", "chahti", "chahte", "ganas"]);
const DYING = new Set(["die", "dying", "morir", "morirme", "morrer", "mourir", "marna", "marne", "maut"]);
const LIVING = new Set(["live", "living", "vivir", "viver", "vivre", "jeena", "jeene", "jina"]);
const NEGATIONS = new Set(["don", "dont", "not", "no", "never", "não", "nao", "ne", "nahi", "nahin", "na"]);
// Harm turned on oneself, in any form: "cutting myself", "she keeps harming herself".
const HARMS = ["cut", "hurt", "harm", "kill", "burn", "stab", "starv", "hang", "poison"];
const REFLEXIVES = new Set(["myself", "herself", "himself", "themselves", "ourselves", "yourself"]);
// Something swallowed or drunk that must not be: "mere bete ne kerosene pee liya".
const SUBSTANCES = new Set([
  "kerosene", "kerosine", "bleach", "pesticide", "insecticide", "poison", "acid", "phenyl",
  "phenol", "detergent", "veneno", "lejía", "lejia", "cloro", "javel", "battery", "batteries",
  "pila", "pilas", "bateria", "baterias", "pills", "tablets", "pastillas", "pastilhas",
  "comprimidos", "cachets", "goli", "goliyan", "dawai",
]);
const INGESTED = new Set([
  "swallowed", "swallow", "swallowing", "drank", "drunk", "ate", "eaten", "took", "taken",
  "ingested", "pee", "piya", "pi", "peeli", "kha", "khaa", "khali", "khaya", "nigal", "nigla",
  "nigli", "tragó", "trago", "tragado", "tragada", "bebió", "bebio", "tomó", "comió", "comio",
  "engoliu", "engoli", "bebeu", "tomou", "comeu", "avalé", "avale", "bu", "mangé",
]);
// Hurt, or attacked, said of someone: "bhai ka accident ho gaya", "my dad fell".
const INJURIES = new Set([
  "accident", "accidente", "acidente", "burn", "burned", "burnt", "quemado", "quemada", "quemó",
  "queimou", "queimado", "brûlé", "fracture", "fractured", "fractura", "fratura", "injured",
  "hurt", "herido", "herida", "ferido", "ferida", "blessé", "blessée", "bitten", "mordido",
  "stabbed", "shot", "chot", "fell", "gir", "gira", "giri", "gire", "caí", "cayó", "caiu", "tombé",
  "assaulted", "assault", "attacked", "mugged", "beaten", "agredido", "agredida", "agrediu",
  "agressé", "agressée", "golpeó", "golpearon", "maara", "maari", "peeta", "peeti",
]);
// Who or when: the event happened to someone ("ho gaya", "my", "papa", "she").
const EVENT_MARKERS = new Set([
  "ho", "gaya", "gayi", "gaye", "hua", "hui", "happened", "had", "met", "got", "was", "were",
  "i", "me", "my", "we", "our", "he", "she", "his", "her", "him", "they", "mera", "meri",
  "mere", "mujhe", "yo", "mi", "eu", "meu", "minha", "mon", "ma", "je", "tuvo", "teve",
  "papa", "mummy", "mom", "mum", "dad", "beta", "beti", "bete", "bhai", "behen", "didi",
]);

// An emergency or a crisis: self-harm, poisoning, injury, collapse, heart or assault.
function urgent(words) {
  if (hasPhrase(words, CRISIS_PHRASES_BY_FIRST) || hasPhrase(words, EMERGENCY_PHRASES_BY_FIRST)) return true;
  if (words.some((w) => EMERGENCY_STEMS.some((stem) => w.startsWith(stem)))) return true;
  if (words.some((w, i) => REFLEXIVES.has(w) && words.slice(Math.max(0, i - 2), i).some((v) => HARMS.some((h) => v.startsWith(h))))) {
    return true;
  }
  if (words.some((w) => SUBSTANCES.has(w)) && words.some((w) => INGESTED.has(w))) return true;
  if (words.some((w) => INJURIES.has(w)) && words.some((w) => EVENT_MARKERS.has(w) || RELATIONS.has(w))) return true;
  for (let index = 0; index < words.length; index += 1) {
    const near = words.slice(index, index + 4);
    if (near.some((w) => WANTS.has(w)) && near.some((w) => DYING.has(w))) return true;
    const wider = words.slice(index, index + 6);
    if (
      wider.some((w) => NEGATIONS.has(w)) && wider.some((w) => WANTS.has(w)) &&
      wider.some((w, at) => LIVING.has(w) && ((w !== "live" && w !== "living") || (at > 0 && wider[at - 1] === "to"))) // not "live chat"
    ) {
      return true;
    }
  }
  return false;
}

module.exports = {
  CRISIS_PHRASES_BY_FIRST,
  EMERGENCY_STEMS,
  EMERGENCY_PHRASES,
  EMERGENCY_PHRASES_BY_FIRST,
  WANTS,
  DYING,
  LIVING,
  NEGATIONS,
  HARMS,
  REFLEXIVES,
  SUBSTANCES,
  INGESTED,
  INJURIES,
  EVENT_MARKERS,
  urgent,
};
