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

// CRC-32 (the zlib polynomial), the same hash as Python's zlib.crc32, so both SDKs key a
// tailored answer the same way. Written out because zlib.crc32 needs Node 20.15 or 22.2.
const CRC32_POLYNOMIAL = 0xedb88320;
const CRC32_TABLE = Array.from({ length: 256 }, (_, n) => {
  let c = n;
  for (let bit = 0; bit < 8; bit++) c = c & 1 ? CRC32_POLYNOMIAL ^ (c >>> 1) : c >>> 1;
  return c >>> 0;
});

function crc32(bytes) {
  let crc = 0xffffffff;
  for (const byte of bytes) crc = CRC32_TABLE[(crc ^ byte) & 0xff] ^ (crc >>> 8);
  return (crc ^ 0xffffffff) >>> 0;
}
const { DETAIL_TYPES, NOT_GENERAL_TYPES } = require("../understanding/turnFrame.js");

// Facts that tailor an answer to the caller: what they have, how old, where and when.
// Facts that tailor an answer. What the user told (a place, a time, a number) is in `stated`, from fixed
// code; a place or time in an earlier shared question is only its topic ("France").
const TOLD_TYPES = new Set(["condition"]);

const { AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT } = require("../turns/routes.js");
const { ChatRuleSet } = require("./chatRuleSet.js");
const { ChatTurn } = require("../turns/chatTurn.js");
const {
  FUNCTION,
  NUMWORDS,
  toks,
  stem,
  QUESTION_WORDS,
  REFERRING,
  CONTRACTION,
  CLAUSE_START,
  GENERIC_FACT,
  looksIdentifying,
} = require("../understanding/frameWords.js");

// Expiry per question type, in seconds. null = until the knowledge version changes.
const DEFAULT_TTL = { policy: null, how_to: null, product_fact: 24 * 3600, place_fact: 6 * 3600, search: 3600, other: 3600 };

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
    // V1-V10 as rules (src/rules/question), in the three groups this checker runs; rebuilt if the
    // public confidenceFloor is changed later, as the old inline check read it on every turn.
    this._rules = ChatRuleSet.chat(this.confidenceFloor);
    this._rulesFloor = this.confidenceFloor;
  }

  check(frame, turn, state) {
    if (this._rulesFloor !== this.confidenceFloor) {
      this._rules = ChatRuleSet.chat(this.confidenceFloor);
      this._rulesFloor = this.confidenceFloor;
    }
    const chatTurn = new ChatTurn(frame, turn, state);
    const decisive = this._rules.decisive.firstObjection(chatTurn);
    if (decisive) return new Verdict(false, decisive.route, [decisive.reason]);
    let reasons = this._rules.frame.allObjections(chatTurn).map((verdict) => verdict.reason);
    if (reasons.length) return new Verdict(false, RuleChecker._routeFor(frame), reasons);
    reasons = this._rules.question.allObjections(chatTurn).map((verdict) => verdict.reason);
    if (reasons.length) return new Verdict(false, AGENT, reasons);

    const question = frame.question;
    const attrs = this._keyAttributes(frame, state, question);
    const ttl = frame.questionType in this.ttl ? this.ttl[frame.questionType] : this.ttl.other;
    // A language the caller asked for wins over the language this turn happens to be in.
    const language = state.language || frame.language;
    return new Verdict(true, SHARED, [], question, attrs, this.buildKey(question, attrs), ttl,
      this.buildSegment(attrs, language, { told: RuleChecker._tailoring(frame, state, question) }));
  }

  static _routeFor(frame) {
    if (frame.kind === "personal" || frame.kind === "sensitive") return PERSONAL;
    if (frame.kind === "live" || frame.kind === "action") return TOOLS;
    return AGENT;
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
    return carried.length ? crc32(Buffer.from(carried.join(" "))).toString(16).padStart(8, "0") : null;
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
