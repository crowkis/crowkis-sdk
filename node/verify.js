"use strict";

// The rule checker and key builder. Mirrors crowkis/verify.py.
//
// The model says what a turn is; these fixed rules decide what may be shared and under which
// key. They check the frame's structure, never decide meaning from word lists.
//   V1 urgent -> urgent route          V6 every key word grounded in the turn or call state
//   V2 abstained / low confidence      V7 no answer-relevant detail dropped
//   V3 not general / about someone     V8 tier/location in the key only if they change the answer
//   V4 owned record / own purchase     V9 a step of a task in progress goes to the agent
//   V5 identifying details in the key  V10 a follow-up whose key still says "it"/"that" and names nothing

const zlib = require("node:zlib");
const { DETAIL_TYPES, NOT_GENERAL_TYPES } = require("./turn.js");

// Facts that tailor an answer to the caller: what they have, how old, where and when.
// Facts that tailor an answer. What the user told (a place, a time, a number) is in `stated`, from fixed
// code; a place or time in an earlier shared question is only its topic ("France").
const TOLD_TYPES = new Set(["condition"]);

const URGENT = "urgent", TASK = "task", SHARED = "shared", PERSONAL = "personal", TOOLS = "tools", AGENT = "agent";

// Expiry per question type, in seconds. null = until the knowledge version changes.
const DEFAULT_TTL = { policy: null, how_to: null, product_fact: 24 * 3600, place_fact: 6 * 3600, search: 3600, other: 3600 };

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

class Verdict {
  // `segment`: the SEGMENT the answer is stored and looked up under (knowledge version, reply
  // language, region and tier, channel). Answers in different segments never meet.
  constructor(shared, route, reasons = [], question = null, attributes = {}, key = null, ttl = null, segment = null) {
    Object.assign(this, { shared, route, reasons, question, attributes, key, ttl, segment });
  }
}

class RuleChecker {
  constructor({ confidenceFloor = 0.6, ttl = {}, knowledgeVersion = "1", channel = "chat" } = {}) {
    if (!(confidenceFloor >= 0 && confidenceFloor <= 1)) throw new Error(`confidenceFloor must be in 0..1, got ${confidenceFloor}`);
    this.confidenceFloor = confidenceFloor;
    this.ttl = { ...DEFAULT_TTL, ...ttl };
    this.knowledgeVersion = String(knowledgeVersion);
    this.channel = String(channel).split(/\s+/).filter(Boolean).join(" ").toLowerCase() || "chat";
  }

  check(frame, turn, state) {
    const reasons = [];
    if (frame.urgent) return new Verdict(false, URGENT, ["V1_urgent"]);
    if (frame.taskStep || this._answersAgentDuringTask(turn, state)) return new Verdict(false, TASK, ["V9_task_step"]);
    if (frame.abstain || frame.confidence < this.confidenceFloor) reasons.push("V2_uncertain");
    if (frame.kind !== "general" || frame.subject !== "none") reasons.push("V3_not_general");
    if (frame.entities.some((e) => NOT_GENERAL_TYPES.has(e.type))) reasons.push("V4_about_someone");
    const question = frame.question;
    if (!question) reasons.push("V3_no_question");
    if (reasons.length) return new Verdict(false, RuleChecker._routeFor(frame), reasons);

    const low = question.toLowerCase();
    if (frame.identifyingTexts.some((t) => low.includes(t.toLowerCase())) || looksIdentifying(question)) reasons.push("V5_identifying");
    const added = this._ungrounded(question, turn, state);
    if (added.length) reasons.push("V6_ungrounded:" + added.slice(0, 3).join(","));
    // The model says the turn leans on the chat ("how far is it from London?") but the turn or its question
    // says "it" and the question names nothing new from the chat (a neutral "population" names nothing;
    // "Who is their president?" -> "Who is the president?" dropped it): the reference was not resolved. A
    // rewrite that resolved it ("Is it safe to eat pad thai in Thailand?") keeps a filler "it" and is fine.
    const saidList = toks(turn);
    const said = new Set(saidList);
    const qwords = toks(question);
    const named = qwords.some((w) => !said.has(w) && !FUNCTION.has(w) && !QUESTION_WORDS.has(w) && !CONTRACTION.has(w));
    if (frame.usesState && [...qwords, ...saidList].some((w) => REFERRING.has(w)) && !named) reasons.push("V10_unresolved");
    const lost = this._lostDetail(frame, question) || RuleChecker._droppedStatement(state, question);
    if (lost) reasons.push("V7_lost:" + lost);
    if (reasons.length) return new Verdict(false, AGENT, reasons);

    const attrs = this._keyAttributes(frame, state, question);
    const ttl = frame.questionType in this.ttl ? this.ttl[frame.questionType] : this.ttl.other;
    // A language the caller asked for wins over the language this turn happens to be in.
    const language = state.language || frame.language;
    return new Verdict(true, SHARED, [], question, attrs, this.buildKey(question, attrs), ttl,
      this.buildSegment(attrs, language, { told: RuleChecker._tailoring(frame, state, question) }));
  }

  /** While a task is running, a reply to the agent's own question is a step of it. */
  _answersAgentDuringTask(turn, state) {
    return state.task !== "none" && state.lastReply.trimEnd().endsWith("?") && !String(turn || "").includes("?");
  }

  static _routeFor(frame) {
    if (frame.kind === "personal" || frame.kind === "sensitive") return PERSONAL;
    if (frame.kind === "live" || frame.kind === "action") return TOOLS;
    return AGENT;
  }

  _ungrounded(question, turn, state) {
    const source = new Set(toks(turn));
    for (const t of state.groundingSources()) for (const w of toks(t)) source.add(w);
    const stems = new Set([...source].map(stem));
    return toks(question).filter((w) => !FUNCTION.has(w) && !source.has(w) && !stems.has(stem(w)) && !QUESTION_WORDS.has(w));
  }

  _lostDetail(frame, question) {
    const qstems = new Set(toks(question).map(stem));
    const attrText = Object.values(frame.attributes).map((a) => `${a.value} ${a.normalised}`).join(" ").toLowerCase();
    for (const e of frame.entities) {
      if (e.answerRelevant && !e.identifying && DETAIL_TYPES.has(e.type)) {
        const words = toks(e.text).filter((w) => !FUNCTION.has(w));
        if (words.length && !words.some((w) => qstems.has(stem(w))) && !words.some((w) => attrText.includes(w))) return e.text;
      }
    }
    return null;
  }

  // A fact the caller stated in this chat that the question does not carry. Fixed code, so the
  // allergy case never rests on the model having tagged the allergy: the question must keep
  // at least one content word of each such turn. A turn with no readable word (another
  // script) cannot be checked, so it keeps the question private.
  static _droppedStatement(state, question) {
    const qstems = new Set(toks(question).map(stem));
    for (const turn of state.stated) {
      let words = toks(turn).filter((w) => !FUNCTION.has(w) && (w.length > 2 || /^\d+$/.test(w)));
      // "allergies" alone does not carry "allergic to penicillin": the specific word must be there.
      const specific = words.filter((w) => !GENERIC_FACT.has(stem(w)));
      if (specific.length) words = specific;
      if (!words.length || !words.some((w) => qstems.has(stem(w)))) return turn;
      // Every item of a list is carried: "penicillin and peanuts" is not "peanuts".
      const all = toks(turn);
      for (let i = 0; i < all.length; i++) {
        // "and I live alone" starts a new clause; it is not a list.
        if ((all[i] !== "and" && all[i] !== "or") || (i + 1 < all.length && CLAUSE_START.has(all[i + 1]))) continue;
        for (const side of [all.slice(0, i).reverse(), all.slice(i + 1)]) {
          const item = side.find((x) => !FUNCTION.has(x));
          if (item && (item.length > 2 || /^\d+$/.test(item)) && !GENERIC_FACT.has(stem(item)) && !qstems.has(stem(item))) return turn;
        }
      }
    }
    return null;
  }

  // What the question carries from what the caller told (their facts, the details of this turn):
  // a short hash of those words, or null for a question anyone could ask. Two callers with a
  // peanut allergy share answers; peanut and shellfish never do.
  static _tailoring(frame, state, question) {
    const told = [...state.stated,
      ...state.facts.filter((f) => TOLD_TYPES.has(f.split(":")[0])).map((f) => f.split(":").slice(1).join(":")),
      // In the question itself only a condition tailors it ("for someone with a peanut allergy"); a
      // place, time or amount there is part of what anyone could ask.
      ...frame.entities.filter((e) => e.type === "condition" && !e.identifying).map((e) => e.text)];
    const toldStems = new Set(told.flatMap((t) => toks(t)).filter((w) => !FUNCTION.has(w)).map(stem));
    const carried = [...new Set(toks(question).filter((w) => !FUNCTION.has(w)).map(stem))].filter((w) => toldStems.has(w)).sort();
    return carried.length ? (zlib.crc32(Buffer.from(carried.join(" "))) >>> 0).toString(16).padStart(8, "0") : null;
  }

  _keyAttributes(frame, state, question) {
    const attrs = {};
    for (const name of ["segment", "region"]) {
      const attr = frame.attributes[name];
      if (attr && attr.changesAnswer) attrs[name] = attr.normalised;
    }
    // Location rule: a question about a named local place, or a search, carries the call's location.
    if ((frame.questionType === "place_fact" || frame.questionType === "search") && !attrs.region) {
      const region = frame.attributes.region || state.attributes.region;
      if (region) attrs.region = region.normalised;
    }
    // What the question already says keeps it apart by itself ("the capital of France" is not "the
    // capital of Spain"); in the segment too it would only split equal questions.
    const qwords = new Set(toks(question));
    for (const [name, value] of Object.entries(attrs)) {
      // The place itself, all of it, word for word: "goa" of "goa, india"; "new york" is not "new".
      const words = toks(value.split(",")[0]).filter((w) => !FUNCTION.has(w));
      if (words.length && words.every((w) => qwords.has(w))) delete attrs[name];
    }
    return attrs;
  }

  /** The question alone: it is what is embedded and matched, so nothing else may be in its text. */
  buildKey(question, attrs) {
    return question.split(/\s+/).filter(Boolean).join(" ");
  }

  // `kb=<version>;lang=<language>;region=...;segment=...;channel=<channel>[;told=<hash>]`. A new
  // version retires old answers. `told` when the question carries facts the user told (an allergy,
  // an age): "avoid it" for someone with a peanut allergy is wrong for someone who asked only "is pad
  // thai safe?", and a near match would serve it. Tailored answers only meet the same facts.
  buildSegment(attrs, language, { told = null } = {}) {
    let parts = [`kb=${this.knowledgeVersion}`, `lang=${language || "und"}`,
      ...Object.keys(attrs).sort().map((k) => `${k}=${attrs[k]}`), `channel=${this.channel}`];
    if (told) parts.push(`told=${told}`);
    // A value can never add or change a field.
    parts = parts.map((p) => { const at = p.indexOf("="); return p.slice(0, at + 1) + p.slice(at + 1).replace(/[;=]/g, "_"); });
    return parts.map((p) => p.split(/\s+/).filter(Boolean).join(" ")).join(";");
  }
}

module.exports = { RuleChecker, Verdict, DEFAULT_TTL, URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, _FUNCTION: FUNCTION, _NUMWORDS: NUMWORDS };
