"use strict";

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
// Words that name a kind of fact, not which one: "allergies" alone does not carry "allergic to
// penicillin". A heuristic list; a fact made only of them ("I'm allergic.") still counts them.
// Acronyms of things, never of a person ("SIM porting", "a UPI refund"): a capitalised word in a shared
// question that is one of these is no name (v4, misfire B05).
const COMMON_ACRONYMS = new Set([
  "sim", "esim", "upi", "otp", "pin", "emi", "kyc", "gst", "atm", "usb", "api", "faq", "pdf", "sms", "mms", "gdpr",
  "icu", "opd", "ac", "tv", "wifi", "gps", "id", "sso", "csv", "vpn", "url", "ssd", "ram", "cpu", "nfc", "qr",
  "pnr", "ifsc", "neft", "rtgs", "imps", "cod", "eta", "ev", "abs",
]);
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

module.exports = {
  COMMON_ACRONYMS,
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
};
