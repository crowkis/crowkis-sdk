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

const { DETAIL_TYPES, NOT_GENERAL_TYPES } = require("../understanding/turnFrame.js");

const { AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT } = require("../turns/results.js");
const { ChatRuleSet } = require("./chatRuleSet.js");
const { key, keyAttributes, segment, told } = require("../keys/knowledgeSegment.js");
const { ChatTurn } = require("../turns/chat/turn.js");
const {
  FUNCTION,
  NUMWORDS,
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
    const attrs = keyAttributes(frame, state, question);
    const ttl = frame.questionType in this.ttl ? this.ttl[frame.questionType] : this.ttl.other;
    // A language the caller asked for wins over the language this turn happens to be in.
    const language = state.language || frame.language;
    return new Verdict(true, SHARED, [], question, attrs, this.buildKey(question, attrs), ttl,
      this.buildSegment(attrs, language, { told: told(frame, state, question) }));
  }

  static _routeFor(frame) {
    if (frame.kind === "personal" || frame.kind === "sensitive") return PERSONAL;
    if (frame.kind === "live" || frame.kind === "action") return TOOLS;
    return AGENT;
  }

  // Kept for test-chat-node18.js, which calls it; the logic lives in keys/knowledgeSegment.js.
  static _tailoring(frame, state, question) {
    return told(frame, state, question);
  }

  /** The question alone: it is what is embedded and matched, so nothing else may be in its text. */
  buildKey(question, attrs) {
    return key(question);
  }

  // `kb=<version>;lang=<language>;region=...;segment=...;channel=<channel>[;told=<hash>]`. A new
  // version retires old answers. `told` when the question carries facts the user told (an allergy,
  // an age): "avoid it" for someone with a peanut allergy is wrong for someone who asked only "is pad
  // thai safe?", and a near match would serve it. Tailored answers only meet the same facts.
  buildSegment(attrs, language, { told = null } = {}) {
    const fields = [["kb", this.knowledgeVersion], ["lang", language || "und"],
      ...Object.keys(attrs).sort().map((k) => [k, attrs[k]]), ["channel", this.channel]];
    if (told) fields.push(["told", told]);
    return segment(fields);
  }
}

module.exports = { RuleChecker, Verdict, DEFAULT_TTL, URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, _FUNCTION: FUNCTION, _NUMWORDS: NUMWORDS };
