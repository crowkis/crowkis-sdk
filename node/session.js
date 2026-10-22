"use strict";

// CallSession: one call or chat thread on turn understanding v2.2. Mirrors crowkis/session.py.
//
//   understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check -> state update
//
// Routes: urgent (on_urgent hook first) | task | shared (lookup; a miss reads ONLY the question) |
// personal (agent + tools; shapes only phrase verified values) | tools | agent. Never cached
// except shared. Sits next to VoiceSession; existing users are unaffected.

const { CallState, IDENTITIES } = require("./callstate.js");
const { ACTION_CLAIM, EMAIL, LONG_DIGITS } = require("./src/understanding/answerPatterns.js");
const { ChatRuleSet } = require("./src/rules/chatRuleSet.js");
const { ChatCore } = require("./src/turns/chatCore.js");
const { TurnResult } = require("./src/turns/turnResult.js");
const { FILLER } = require("./src/turns/routes.js");
const {
  NAME_LEADS,
  SELF_INTRO,
  RELATIONS,
  POSSESSIVE,
  TITLES,
  names,
  told,
  privateWords,
  REPLY_WORD,
  MASKED,
  masked,
  norm,
} = require("./src/understanding/chatDetails.js");
const { CacheLookup } = require("./src/runtime/cacheLookup.js");
const { CHAT } = require("./src/turns/channel.js");
// Chat's counter for each way a lookup fails open.
const LOOKUP_COUNTS = { LookupDeadline: "lookup_timeouts", CacheUnavailable: "lookup_errors" };
const { ChatAnswer } = require("./src/turns/chatAnswer.js");
const { ChatTurn } = require("./src/turns/chatTurn.js");
const { UrgentWords } = require("./src/rules/question/index.js");
const { CALENDAR } = require("./src/understanding/frameWords.js");
const {
  _tellsAboutCaller: tellsAboutCaller, _instructs: instructs,
  _wordsOf: wordsOf, _properNouns: properNouns,
  _PII_PLACEHOLDER: PII_PLACEHOLDER,
} = require("./voice.js");
const { TurnFrame } = require("./turn.js");
const { _FUNCTION: FUNCTION, AGENT, PERSONAL, RuleChecker, SHARED, TASK, TOOLS, URGENT, Verdict } = require("./verify.js");

const MODES = ["full", "replay_only", "off"];
class CallSession {
  /**
   * @param agent        a crowkis Agent (async ask / learn)
   * @param understander anything with understand(turn, state) -> TurnFrame (sync or async)
   * @param options      checker, onUrgent(turn, frame), replay, serveAbove, latencyBudgetMs,
   *                     understandBudgetMs, fillers, mode ("full" | "replay_only" | "off"), onEvent(event),
   *                     instructions (the system prompt the model reads with a shared question: a
   *                     shared answer repeating a detail it gives about this caller is never saved,
   *                     "refused:prompt_detail")
   */
  constructor(agent, understander, options = {}) {
    const {
      checker = null, onUrgent = null, replay = null, serveAbove = 0.92,
      latencyBudgetMs = 300, understandBudgetMs = 250, fillers = {}, mode = "full", onEvent = null,
      urgentReply = null, onTools = null, instructions = "",
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
    // The business's pre-approved reply to an emergency (its helplines); without one the model
    // answers with the whole call. Never cached either way.
    this.urgentReply = String(urgentReply || "").trim() || null;
    // The business's own system for "my balance", "my booking": returns the reply, or null for
    // the model to answer with the whole call. Never cached.
    this.onTools = onTools;
    this.instructions = String(instructions || "").trim();
    this.setMode(mode);
    this.state = new CallState();
    // A chat: what it can do. Its turn steps (ChatCore) own its lookup inside the budget (a late hit is
    // still served, as before), its rule chains and its turns; this session keeps state, counts and hooks.
    this.channel = CHAT;
    this._core = new ChatCore(this, {
      cacheLookup: new CacheLookup({ refuseLateHits: false }), sharedQuestionRules: ChatRuleSet.sharedQuestionChain(),
      urgentWords: new UrgentWords(), saveRules: ChatRuleSet.saveChain(),
    });
    this._fillers = new Map(Object.entries(fillers || {}).map(([k, v]) => [norm(k), v]));
    this._shapes = new Map();
    this.counts = Object.fromEntries([URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved",
      "save_refused", "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
      "cancelled", "sharing_off", "tools_answered"].map((k) => [k, 0]));
  }

  /** Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing). */
  setMode(mode) {
    if (!MODES.includes(mode)) throw new Error(`mode must be one of ${MODES.join(", ")}, got ${mode}`);
    this.mode = mode;
  }


  /** The agent answered `result`. Saves when allowed, updates the call state. Returns the outcome. */
  handle(turn) {
    return this._core.handle(turn);
  }

  /** Barge-in: the open turn is abandoned and its answer will never be saved. */
  cancel() {
    return this._core.cancel();
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null) {
    return this._core.saveCheck(answer, verdict, frame);
  }

  /** The cached answer for a shared key, or null (kept for code that calls it; ChatCore looks up). */
  _lookup(key, segment) {
    return this._core._lookup(key, segment);
  }

  /** Registered fillers, by normalised trigger. */
  get fillers() {
    return this._fillers;
  }

  /** Send a monitoring event (never throws). */
  emit(event) {
    this._emit(event);
  }

  /** Whose system prompts this chat's is compared with. */
  promptKey() {
    return this._promptKey();
  }

  async recordAnswer(result, answer, { mentions = [], task = null } = {}) {
    const outcome = await this._core.record(result, answer, mentions, task);
    this._emit({ type: "answer", turnId: result.turnId, route: result.route, outcome, key: result.verdict ? result.verdict.key : null });
    return outcome;
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


  // Which system prompts this call's is compared with: the same agent's on the same channel
  // (a chat's prompt never stands in for a voice call's).
  _promptKey() {
    const agent = this.agent || {};
    return [agent.tenant || (agent.client && agent.client.tenant) || null, agent.agentId || null, (this.checker && this.checker.channel) || null];
  }

  /** The thread's memory for the app's store, between turns. No transcript is in it. */
  export() {
    return { version: 1, state: this.state.toDict(), next_turn: this._core.nextTurn };
  }

  /** A session for the next turn of a thread saved with `export`. Damaged data starts fresh; never throws. */
  static restore(agent, understander, data, options = {}) {
    const session = new CallSession(agent, understander, options);
    data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
    session.state = CallState.fromDict(data.state);
    const next = Number.parseInt(data.next_turn, 10);
    if (Number.isFinite(next) && next >= 1) session._core.nextTurn = next;
    return session;
  }

  stats() {
    return { ...this.counts };
  }



  _emit(event) {
    if (!this.onEvent) return;
    try { this.onEvent(event); } catch { /* monitoring must never affect the call */ }
  }

}

module.exports = { CallSession, TurnResult, FILLER, MODES, _masked: masked };
