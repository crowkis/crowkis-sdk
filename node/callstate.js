"use strict";

// Call state: what the agent remembers about one call, as structure, not transcript.
// Mirrors crowkis/callstate.py. Fillers never change it; a fact said at turn 2 still counts
// at turn 40; the agent's own words ("that hotel") stay resolvable. No I/O.

const crypto = require("node:crypto");
const { Attribute } = require("./turn.js");

const TASKS = ["none", "searching", "booking", "ordering", "account_action"];
const IDENTITIES = ["anonymous", "identified", "verified"];
const MAX_FACTS = 10;
const MAX_MENTIONS = 10;
const MAX_STATED = 10;
const MAX_PRIVATE_WORDS = 64;
// Every kept text (a fact, the last reply, the open question) is cut to this, so a thread's memory
// stays a few KB whatever a user sends or a store hands back.
const MAX_TEXT = 1000;

function clean(t) {
  if (t === null || t === undefined) return "";
  // Counted in characters (code points), as Python counts them.
  const joined = Array.from(String(t).slice(0, MAX_TEXT * 8)).slice(0, MAX_TEXT * 4).join("").split(/\s+/).filter(Boolean).join(" ");
  return Array.from(joined).slice(0, MAX_TEXT).join("");
}

// A saved list of strings, or nothing: damaged saved data never breaks a thread.
function strings(v) {
  return Array.isArray(v) ? v.filter((x) => typeof x === "string").map(clean).filter(Boolean) : [];
}

function wordDigest(word) {
  word = clean(word).toLowerCase();
  return word ? crypto.createHash("sha256").update(word, "utf8").digest("hex").slice(0, 16) : "";
}

class CallState {
  constructor(init = {}) {
    this.activeQuestion = init.activeQuestion ?? null;
    this.activeKind = init.activeKind ?? null;
    this.facts = [...(init.facts || [])];
    this.agentMentions = [...(init.agentMentions || [])];
    this.task = init.task || "none";
    this.attributes = { ...(init.attributes || {}) };
    this.subjectFocus = "none";
    this.identity = "anonymous";
    this.lastReply = clean(init.lastReply || "");
    // The reply language the caller asked for ("reply only in Hindi"), set only by that request.
    this.language = init.language ?? null;
    // What the caller told that a later answer depends on ("allergic peanuts"), as the turn's words
    // without names or long numbers: a shared question must carry them. Never sent anywhere.
    this.stated = [...(init.stated || [])];
    // Hashes of words that identified the caller in turns that were not shared ("sarah", "55512"):
    // a shared answer holding one is refused. Hashed, so the words are not kept.
    this.privateWords = [...(init.privateWords || [])];
    // Hashes of what named the caller (a name given, an email, a long number): a shared question
    // saying one is never shared. Narrower than privateWords, which only refuses answers.
    this.names = [...(init.names || [])];
    // Hashes of the specific words of facts the caller told (a place, a month, a number: "goa",
    // "december", "3"): a shared question must carry every one, or it stays private.
    this.details = [...(init.details || [])];
  }

  /** Record what the agent said, the things it named or offered, and the task it runs (set by the app). */
  noteAgentReply(t, mentions = [], task = null) {
    this.lastReply = clean(t);
    for (const raw of mentions || []) {
      const item = clean(raw);
      if (item && !this.agentMentions.includes(item)) this.agentMentions.push(item);
    }
    this.agentMentions = this.agentMentions.slice(-MAX_MENTIONS);
    if (task !== null && task !== undefined) this.startTask(task);
  }

  startTask(task) {
    task = String(task || "none").toLowerCase();
    this.task = TASKS.includes(task) ? task : "none";
  }

  endTask() {
    this.task = "none";
  }

  /** Set by the app after its own checks; the cache never infers it. */
  setIdentity(identity) {
    identity = String(identity || "").toLowerCase();
    if (!IDENTITIES.includes(identity)) throw new Error(`identity must be one of ${IDENTITIES.join(", ")}, got ${identity}`);
    this.identity = identity;
  }

  /** Update from a caller turn's frame once the rule checker ruled on it (`shared`). */
  apply(frame, { shared }) {
    if (frame.abstain) {
      // The caller referred to something we cannot see: never resolve against a stale question.
      // Checked first: a bare "what about that?" with no details must still clear it.
      this.activeQuestion = null;
      this.activeKind = "dialogue";
      return;
    }
    if (frame.isPureAcknowledgement) return;
    if (frame.kind === "general" && shared && frame.question) {
      this.activeQuestion = frame.question;
      this.activeKind = "general";
      if (!frame.taskStep) this.endTask();
    } else {
      this.activeKind = frame.kind;
    }
    if (frame.kind === "action" && this.task === "none") this.task = "account_action";
    if (frame.subject === "self" || frame.subject === "other") this.subjectFocus = frame.subject;
    for (const e of frame.memorable) {
      const fact = `${e.type}: ${e.text}`;
      const at = this.facts.indexOf(fact);
      if (at >= 0) this.facts.splice(at, 1);
      this.facts.push(fact);
    }
    this.facts = this.facts.slice(-MAX_FACTS);
    for (const [name, attr] of Object.entries(frame.attributes)) {
      if (name === "segment" || name === "region") this.attributes[name] = attr;
    }
  }

  noteStated(turn) {
    turn = clean(turn);
    if (turn && !this.stated.includes(turn)) this.stated.push(turn);
    this.stated = this.stated.slice(-MAX_STATED);
  }

  notePrivate(words) {
    for (const raw of words || []) {
      const digest = wordDigest(raw);
      if (digest && !this.privateWords.includes(digest)) this.privateWords.push(digest);
    }
    this.privateWords = this.privateWords.slice(-MAX_PRIVATE_WORDS);
  }

  isPrivate(word) {
    return this.privateWords.includes(wordDigest(word));
  }

  noteNames(words) {
    for (const raw of words || []) {
      const digest = wordDigest(raw);
      if (digest && !this.names.includes(digest)) this.names.push(digest);
    }
    this.names = this.names.slice(-MAX_PRIVATE_WORDS);
  }

  isName(word) {
    return this.names.includes(wordDigest(word));
  }

  noteDetails(words) {
    for (const raw of words || []) {
      const digest = wordDigest(raw);
      if (digest && !this.details.includes(digest)) this.details.push(digest);
    }
    this.details = this.details.slice(-MAX_PRIVATE_WORDS);
  }

  /** Everything, for the app's own store: a stateless chat server restores it per request. */
  toDict() {
    const attributes = {};
    for (const [k, a] of Object.entries(this.attributes)) {
      attributes[k] = { value: a.value, normalised: a.normalised, changes_answer: a.changesAnswer };
    }
    return {
      active_question: this.activeQuestion,
      active_kind: this.activeKind,
      facts: [...this.facts],
      agent_mentions: [...this.agentMentions],
      task: this.task,
      attributes,
      subject_focus: this.subjectFocus,
      identity: this.identity,
      last_reply: this.lastReply,
      language: this.language,
      stated: [...this.stated],
      private_words: [...this.privateWords],
      names: [...this.names],
      details: [...this.details],
    };
  }

  /** Rebuild from `toDict`. Anything missing or malformed starts empty; never throws. */
  static fromDict(data) {
    data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
    const list = strings;
    const state = new CallState();
    state.activeQuestion = clean(data.active_question) || null;
    state.activeKind = clean(data.active_kind) || null;
    state.facts = list(data.facts).slice(-MAX_FACTS);
    state.agentMentions = list(data.agent_mentions).slice(-MAX_MENTIONS);
    state.startTask(clean(data.task));
    const attributes = data.attributes && typeof data.attributes === "object" ? data.attributes : {};
    for (const [name, raw] of Object.entries(attributes)) {
      const attr = Attribute.fromDict(raw);
      if (attr && (name === "segment" || name === "region")) state.attributes[name] = attr;
    }
    state.subjectFocus = clean(data.subject_focus) || "none";
    const identity = clean(data.identity).toLowerCase();
    state.identity = IDENTITIES.includes(identity) ? identity : "anonymous";
    state.lastReply = clean(data.last_reply);
    state.language = clean(data.language).toLowerCase().slice(0, 32) || null;
    for (const turn of list(data.stated)) state.noteStated(turn);
    state.privateWords = list(data.private_words).filter((d) => d.length === 16).slice(-MAX_PRIVATE_WORDS);
    state.names = list(data.names).filter((d) => d.length === 16).slice(-MAX_PRIVATE_WORDS);
    state.details = list(data.details).filter((d) => d.length === 16).slice(-MAX_PRIVATE_WORDS);
    return state;
  }

  /** The de-identified state sent with each turn: no caller transcript, no identity. */
  snapshot() {
    const attributes = {};
    for (const [k, a] of Object.entries(this.attributes)) attributes[k] = { value: a.value, normalised: a.normalised };
    return {
      active_question: this.activeQuestion,
      active_kind: this.activeKind,
      facts: [...this.facts],
      agent_mentions: [...this.agentMentions],
      task: this.task,
      attributes,
      last_reply: this.lastReply,
      language: this.language,
    };
  }

  /** Text the shared question may draw its words from, besides the turn itself. */
  groundingSources() {
    // the caller's own words count
    return [this.activeQuestion || "", this.lastReply, ...this.facts, ...this.agentMentions, ...this.stated].filter(Boolean);
  }

  clone() {
    const c = new CallState({
      activeQuestion: this.activeQuestion, activeKind: this.activeKind, facts: this.facts,
      agentMentions: this.agentMentions, task: this.task, attributes: this.attributes, lastReply: this.lastReply,
      language: this.language, stated: this.stated, privateWords: this.privateWords, names: this.names, details: this.details,
    });
    c.subjectFocus = this.subjectFocus;
    c.identity = this.identity;
    return c;
  }
}

module.exports = { CallState, TASKS, IDENTITIES, Attribute, wordDigest };
