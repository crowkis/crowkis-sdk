"use strict";

// The rule checker and key builder. Mirrors crowkis/verify.py.
//
// The model says what a turn is; these fixed rules decide what may be shared and under which
// key. They check the frame's structure, never decide meaning from word lists.
//   V1 urgent -> urgent route          V6 every key word grounded in the turn or call state
//   V2 abstained / low confidence      V7 no answer-relevant detail dropped
//   V3 not general / about someone     V8 tier/location in the key only if they change the answer
//   V4 owned record / own purchase     V9 a step of a task in progress goes to the agent
//   V5 identifying details in the key

const { DETAIL_TYPES, NOT_GENERAL_TYPES } = require("./turn.js");

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
tell find found look looking show give know serve serves served recommend suggest`.split(/\s+/));

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
  if (w.length > 3 && w.endsWith("e")) w = w.slice(0, -1);
  if (w.length > 3 && (w.endsWith("y") || w.endsWith("i"))) w = w.slice(0, -1);
  return w;
}

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
  constructor(shared, route, reasons = [], question = null, attributes = {}, key = null, ttl = null) {
    Object.assign(this, { shared, route, reasons, question, attributes, key, ttl });
  }
}

class RuleChecker {
  constructor({ confidenceFloor = 0.6, ttl = {}, knowledgeVersion = "1" } = {}) {
    if (!(confidenceFloor >= 0 && confidenceFloor <= 1)) throw new Error(`confidenceFloor must be in 0..1, got ${confidenceFloor}`);
    this.confidenceFloor = confidenceFloor;
    this.ttl = { ...DEFAULT_TTL, ...ttl };
    this.knowledgeVersion = String(knowledgeVersion);
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
    const lost = this._lostDetail(frame, question);
    if (lost) reasons.push("V7_lost:" + lost);
    if (reasons.length) return new Verdict(false, AGENT, reasons);

    const attrs = this._keyAttributes(frame, state);
    const ttl = frame.questionType in this.ttl ? this.ttl[frame.questionType] : this.ttl.other;
    return new Verdict(true, SHARED, [], question, attrs, this.buildKey(question, attrs), ttl);
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
    return toks(question).filter((w) => !FUNCTION.has(w) && !source.has(w) && !stems.has(stem(w)));
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

  _keyAttributes(frame, state) {
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
    return attrs;
  }

  /** `[kb=<version>; region=...; segment=...] <question>`: one key per meaning, tier, place and version. */
  buildKey(question, attrs) {
    const parts = [`kb=${this.knowledgeVersion}`, ...Object.keys(attrs).sort().map((k) => `${k}=${attrs[k]}`)];
    return `[${parts.join("; ")}] ${question.split(/\s+/).filter(Boolean).join(" ")}`;
  }
}

module.exports = { RuleChecker, Verdict, DEFAULT_TTL, URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT };
