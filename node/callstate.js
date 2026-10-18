"use strict";

// Call state: what the agent remembers about one call, as structure, not transcript.
// Mirrors crowkis/callstate.py. Fillers never change it; a fact said at turn 2 still counts
// at turn 40; the agent's own words ("that hotel") stay resolvable. No I/O.

const { Attribute } = require("./turn.js");

const TASKS = ["none", "searching", "booking", "ordering", "account_action"];
const IDENTITIES = ["anonymous", "identified", "verified"];
const MAX_FACTS = 10;
const MAX_MENTIONS = 10;

function clean(t) {
  return t === null || t === undefined ? "" : String(t).split(/\s+/).filter(Boolean).join(" ");
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
    };
  }

  /** Text the shared question may draw its words from, besides the turn itself. */
  groundingSources() {
    return [this.activeQuestion || "", this.lastReply, ...this.facts, ...this.agentMentions].filter(Boolean);
  }

  clone() {
    const c = new CallState({
      activeQuestion: this.activeQuestion, activeKind: this.activeKind, facts: this.facts,
      agentMentions: this.agentMentions, task: this.task, attributes: this.attributes, lastReply: this.lastReply,
    });
    c.subjectFocus = this.subjectFocus;
    c.identity = this.identity;
    return c;
  }
}

module.exports = { CallState, TASKS, IDENTITIES, Attribute };
