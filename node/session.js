"use strict";

// CallSession: one call or chat thread on turn understanding v2.2. Mirrors crowkis/session.py.
//
//   understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check -> state update
//
// Routes: urgent (on_urgent hook first) | task | shared (lookup; a miss reads ONLY the question) |
// personal (agent + tools; shapes only phrase verified values) | tools | agent. Never cached
// except shared. Sits next to VoiceSession; existing users are unaffected.

const { CallState, IDENTITIES } = require("./callstate.js");
const { isNonAnswer } = require("./rules.js");
const { TurnFrame } = require("./turn.js");
const { AGENT, PERSONAL, RuleChecker, SHARED, TASK, TOOLS, URGENT } = require("./verify.js");

const FILLER = "filler";
const MODES = ["full", "replay_only", "off"];
const TIMEOUT = Symbol("timeout");
const EMAIL = /\S+@\S+/;
const LONG_DIGITS = /\d(?:[\s-]?\d){5,}/;
// A first-person claim that something was done: a cached answer must never claim an action.
const ACTION_CLAIM = new RegExp(
  "\\b(i\\s*(have|'ve)|i\\s+just|we\\s*(have|'ve))\\s+(cancel+ed|booked|refunded|processed|changed|updated|" +
  "reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\\b" +
  "|\\b(has|have)\\s+been\\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted)\\b", "i");

/** Resolve within `ms`, else TIMEOUT. The late promise keeps running and is ignored. */
function within(promiseOrValue, ms) {
  const work = Promise.resolve(promiseOrValue);
  if (ms === null || ms === undefined) return work;
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve(TIMEOUT), ms); });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}

function norm(t) {
  return String(t || "").toLowerCase().replace(/^[\s\p{P}]+|[\s\p{P}]+$/gu, "").split(/\s+/).filter(Boolean).join(" ");
}

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

class TurnResult {
  constructor(turnId, route, fields = {}) {
    this.turnId = turnId;
    this.route = route;
    this.text = fields.text ?? null;            // what to say now (cache hit or filler)
    this.needsModel = fields.needsModel ?? true;
    this.messages = fields.messages ?? null;    // what the model reads; null = the whole call
    this.frame = fields.frame ?? null;
    this.verdict = fields.verdict ?? null;
    this.reason = fields.reason ?? "";
  }

  get servedFromCache() {
    return this.route === SHARED && this.text !== null;
  }
}

class CallSession {
  /**
   * @param agent        a crowkis Agent (async ask / learn)
   * @param understander anything with understand(turn, state) -> TurnFrame (sync or async)
   * @param options      checker, onUrgent(turn, frame), replay, serveAbove, latencyBudgetMs,
   *                     understandBudgetMs, fillers, mode ("full" | "replay_only" | "off"), onEvent(event)
   */
  constructor(agent, understander, options = {}) {
    const {
      checker = null, onUrgent = null, replay = null, serveAbove = 0.92,
      latencyBudgetMs = 300, understandBudgetMs = 250, fillers = {}, mode = "full", onEvent = null,
    } = options;
    for (const [name, value] of [["latencyBudgetMs", latencyBudgetMs], ["understandBudgetMs", understandBudgetMs]]) {
      if (value !== null && value !== undefined && !(value > 0)) throw new Error(`${name} must be positive or null, got ${value}`);
    }
    this.agent = agent;
    this.understander = understander;
    this.checker = checker || new RuleChecker();
    this.onUrgent = onUrgent;
    this.replay = replay;
    this.serveAbove = serveAbove;
    this.latencyBudgetMs = latencyBudgetMs;
    this.understandBudgetMs = understandBudgetMs;
    this.onEvent = onEvent;
    this.setMode(mode);
    this.state = new CallState();
    this._fillers = new Map(Object.entries(fillers || {}).map(([k, v]) => [norm(k), v]));
    this._shapes = new Map();
    this._nextId = 1;
    this._open = null;
    this._cancelled = new Set();
    this.counts = Object.fromEntries([URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved",
      "save_refused", "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
      "cancelled", "sharing_off"].map((k) => [k, 0]));
  }

  /** Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing). */
  setMode(mode) {
    if (!MODES.includes(mode)) throw new Error(`mode must be one of ${MODES.join(", ")}, got ${mode}`);
    this.mode = mode;
  }

  async handle(turn) {
    const tid = this._nextId++;
    const t = String(turn || "").split(/\s+/).filter(Boolean).join(" ");
    if (!t) return this._openTurn(new TurnResult(tid, AGENT, { reason: "empty" }));
    const filler = this._fillers.get(norm(t));
    if (filler !== undefined) {
      this.counts[FILLER] += 1;
      this.state.noteAgentReply(filler);
      return new TurnResult(tid, FILLER, { text: filler, needsModel: false, reason: "registered filler" });
    }
    if (this.mode === "off") {
      this.counts.sharing_off += 1;
      this._emit({ type: "turn", turnId: tid, route: AGENT, reasons: ["mode_off"], shared: false });
      return this._openTurn(new TurnResult(tid, AGENT, { reason: "sharing off" }));
    }

    const frame = await this._understand(t);
    const verdict = this.checker.check(frame, t, this.state);
    this.state.apply(frame, { shared: verdict.shared });
    this.counts[verdict.route] += 1;
    if (verdict.route === URGENT && this.onUrgent) {
      try { await this.onUrgent(t, frame); } catch { /* the hook must not take the call down */ }
    }
    const event = {
      type: "turn", turnId: tid, route: verdict.route, reasons: [...verdict.reasons], shared: verdict.shared,
      urgent: frame.urgent, kind: frame.kind, confidence: frame.confidence, question: verdict.question,
      key: verdict.key, questionType: verdict.shared ? frame.questionType : null,
    };
    if (verdict.route !== SHARED) {
      this._emit({ ...event, hit: false });
      return this._openTurn(new TurnResult(tid, verdict.route, { frame, verdict, reason: verdict.reasons.join(";") }));
    }
    if (this.replay) this.replay.remember(t, verdict.question, frame.questionType);
    const hit = await this._lookup(verdict.key);
    if (hit !== null) {
      this.counts.hits += 1;
      this.state.noteAgentReply(hit);
      this._emit({ ...event, hit: true });
      return this._openTurn(new TurnResult(tid, SHARED, { text: hit, needsModel: false, frame, verdict, reason: "cache hit" }));
    }
    this._emit({ ...event, hit: false });
    const messages = [{ role: "user", content: verdict.question }];
    const attrs = Object.entries(verdict.attributes).sort();
    if (attrs.length) messages.unshift({ role: "system", content: `Answer for: ${attrs.map(([k, v]) => `${k}: ${v}`).join("; ")}.` });
    return this._openTurn(new TurnResult(tid, SHARED, { frame, verdict, messages, reason: "cache miss" }));
  }

  /** The agent answered `result`. Saves when allowed, updates the call state. Returns the outcome. */
  async recordAnswer(result, answer, { mentions = [], task = null } = {}) {
    const outcome = await this._record(result, answer, mentions, task);
    this._emit({ type: "answer", turnId: result.turnId, route: result.route, outcome, key: result.verdict ? result.verdict.key : null });
    return outcome;
  }

  async _record(result, answer, mentions, task) {
    if (this._cancelled.has(result.turnId)) { this.counts.cancelled += 1; return "cancelled"; }
    if (!this._open || this._open.turnId !== result.turnId) return "stale";
    this._open = null;
    this.state.noteAgentReply(answer, mentions, task);
    if (result.route !== SHARED || result.text !== null || !result.verdict) return "not_shared";
    const why = this.saveCheck(answer, result.verdict, result.frame);
    if (why) { this.counts.save_refused += 1; return "refused:" + why; }
    try {
      await this.agent.learn(result.verdict.key, answer, { ttl: result.verdict.ttl ?? undefined });
    } catch {
      this.counts.save_refused += 1;
      return "refused:write_failed";
    }
    this.counts.saved += 1;
    return "saved";
  }

  /** Barge-in: the open turn is abandoned and its answer will never be saved. */
  cancel() {
    if (!this._open) return false;
    this._cancelled.add(this._open.turnId);
    this._open = null;
    return true;
  }

  /** A response shape for one field returned by the agent's own tools. */
  registerShape(field, template, { requires = "identified" } = {}) {
    if (!IDENTITIES.includes(requires)) throw new Error(`requires must be one of ${IDENTITIES.join(", ")}`);
    if (!template.includes(`{${field}}`)) throw new Error("the template must contain the field's own slot");
    this._shapes.set(field, { template, requires });
  }

  /** Phrase a value the agent's tool returned; null without a shape, enough verification, or for someone else. */
  phrase(field, value, { subject = "self" } = {}) {
    const shape = this._shapes.get(field);
    if (!shape || subject !== "self" || value === null || value === undefined || value === "") return null;
    if (IDENTITIES.indexOf(this.state.identity) < IDENTITIES.indexOf(shape.requires)) return null;
    return shape.template.split(`{${field}}`).join(String(value));
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null) {
    const t = String(answer || "").split(/\s+/).filter(Boolean).join(" ");
    if (!t) return "empty";
    if (isNonAnswer(t)) return "non_answer";
    if (EMAIL.test(t) || LONG_DIGITS.test(t)) return "identifying";
    if (frame && frame.identifyingTexts.some((x) => t.toLowerCase().includes(x.toLowerCase()))) return "identifying";
    if (ACTION_CLAIM.test(t)) return "action_claim";
    for (const [name, attr] of Object.entries(this.state.attributes)) {
      if (!(name in verdict.attributes) && attr.value && new RegExp(`\\b${escapeRe(attr.value)}\\b`, "i").test(t)) {
        return "attribute_not_in_key";
      }
    }
    return null;
  }

  stats() {
    return { ...this.counts };
  }

  async _understand(t) {
    if (this.mode === "replay_only") {
      if (!this.replay) return TurnFrame.fromDict(null);
      this.counts.fallback_used += 1;
      return this.replay.understand(t, this.state);
    }
    try {
      // The model gets its own copy of the state: a late answer can never see a later turn's state.
      const frame = await within(this.understander.understand(t, this.state.clone()), this.understandBudgetMs);
      if (frame !== TIMEOUT) return frame || TurnFrame.fromDict(null);
      this.counts.understand_timeouts += 1;
    } catch {
      this.counts.understand_errors += 1;
    }
    if (this.replay && this.replay !== this.understander) {
      this.counts.fallback_used += 1;
      try { return this.replay.understand(t, this.state); } catch { /* fall through */ }
    }
    return TurnFrame.fromDict(null);
  }

  async _lookup(key) {
    try {
      const hit = await within(this.agent.ask(key, { serveAbove: this.serveAbove, cheapAbove: Math.min(0.6, this.serveAbove) }),
        this.latencyBudgetMs);
      if (hit === TIMEOUT) { this.counts.lookup_timeouts += 1; return null; }
      return hit && hit.route === "cache" && hit.answer ? hit.answer : null;
    } catch {
      this.counts.lookup_errors += 1;
      return null;
    }
  }

  _emit(event) {
    if (!this.onEvent) return;
    try { this.onEvent(event); } catch { /* monitoring must never affect the call */ }
  }

  _openTurn(result) {
    this._open = result;
    return result;
  }
}

module.exports = { CallSession, TurnResult, FILLER, MODES };
