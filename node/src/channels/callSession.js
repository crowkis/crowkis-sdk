"use strict";

// CallSession: one call or chat thread on turn understanding v2.2. Mirrors crowkis/session.py.
//
//   understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check -> state update
//
// Routes: urgent (on_urgent hook first) | task | shared (lookup; a miss reads ONLY the question) |
// personal (agent + tools; shapes only phrase verified values) | tools | agent. Never cached
// except shared. Sits next to VoiceSession; existing users are unaffected.

const { CallState, IDENTITIES } = require("../state/callState.js");
const { ACTION_CLAIM, EMAIL, LONG_DIGITS } = require("../understanding/answerPatterns.js");
const { ChatRuleSet } = require("../rules/chatRuleSet.js");
const { TurnCore } = require("../turns/core.js");
const { ChatAnswered } = require("../turns/results.js");
const { ChatAnswers, eventHook } = require("../turns/chat/steps.js");
const { ChatHitCheck } = require("../turns/chat/checks.js");
const { ChatQuestionCheck } = require("../turns/chat/checks.js");
const { ChatReader } = require("../turns/chat/turn.js");
const { ChatReading } = require("../turns/chat/turn.js");
const { ChatReport } = require("../turns/chat/steps.js");
const { ChatSaving } = require("../turns/chat/steps.js");
const { ChatTurns } = require("../turns/chat/steps.js");
const { TurnResult } = require("../turns/results.js");
const { FILLER } = require("../turns/results.js");
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
} = require("../understanding/chatDetails.js");
const { CacheLookup } = require("../runtime/cacheLookup.js");
const { QuestionRecords } = require("../runtime/questionRecords.js");
const { BoundedWriter } = require("../runtime/boundedWriter.js");
// BoundedWriter's counters, under Chat's names.
const WRITE_COUNTS = { slowWrites: "slow_writes", learnErrors: "learn_errors" };
const { CHAT } = require("../turns/values.js");
// A chat's counters for each way a lookup fails open.
const LOOKUP_DEADLINE_COUNTS = ["lookup_timeouts"];
const LOOKUP_UNAVAILABLE_COUNTS = ["lookup_errors"];
const { ChatAnswer } = require("../turns/chat/turn.js");
const { ChatTurn } = require("../turns/chat/turn.js");
const { UrgentWords } = require("../rules/question/index.js");
const { CALENDAR } = require("../understanding/frameWords.js");
const {
  _tellsAboutCaller: tellsAboutCaller, _instructs: instructs,
  _wordsOf: wordsOf, _properNouns: properNouns,
  _trackRecord: trackRecord, _pendingWrites: pendingWrites, _writesMax: writesMax,
} = require("./voiceSession.js");
const { TurnFrame } = require("../understanding/turnFrame.js");
const { _FUNCTION: FUNCTION, AGENT, PERSONAL, RuleChecker, SHARED, TASK, TOOLS, URGENT, Verdict } = require("../rules/ruleChecker.js");

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
    // A chat: what it can do. This session keeps the chat's state, counts, settings and hooks.
    this.channel = CHAT;
    this._fillers = new Map(Object.entries(fillers || {}).map(([k, v]) => [norm(k), v]));
    this._shapes = new Map();
    this.counts = Object.fromEntries([URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved",
      "save_refused", "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
      "cancelled", "sharing_off", "tools_answered"].map((k) => [k, 0]));
    this._core = this._buildCore();
  }

  /**
   * The one TurnCore with a chat's parts (this session is their composition root). Its lookup serves a
   * late hit, as Chat always did.
   */
  _buildCore() {
    this._turns = new ChatTurns();
    this._report = new ChatReport(this, this._turns);
    const records = new QuestionRecords(this.agent, { track: trackRecord });
    this._cacheLookup = new CacheLookup({
      refuseLateHits: false, deadlineCounts: LOOKUP_DEADLINE_COUNTS, unavailableCounts: LOOKUP_UNAVAILABLE_COUNTS,
    });
    this._saving = new ChatSaving(this, {
      saveRules: ChatRuleSet.saveChain(), questionRecords: records, report: this._report,
      writer: new BoundedWriter(pendingWrites, writesMax, (counter) => this._countWrite(counter), (message) => console.warn(message)),
    });
    const questionCheck = new ChatQuestionCheck(this, {
      sharedQuestionRules: ChatRuleSet.sharedQuestionChain(), urgentWords: new UrgentWords(),
    });
    const hitCheck = new ChatHitCheck(this, { hitRules: ChatRuleSet.hitChain(), questionRecords: records });
    return new TurnCore(this, {
      pairing: this._turns, answers: new ChatAnswers(this, this._turns),
      reader: new ChatReader(this), questionCheck,
      cacheLookup: this._cacheLookup, hitCheck, report: this._report, saving: this._saving,
    });
  }

  /** Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing). */
  setMode(mode) {
    if (!MODES.includes(mode)) throw new Error(`mode must be one of ${MODES.join(", ")}, got ${mode}`);
    this.mode = mode;
  }


  /** One user turn: an early answer, a cached answer, or the agent's turn (a TurnResult). */
  handle(turn) {
    return this._core.decide(turn);
  }

  /** Barge-in: the open turn is abandoned and its answer will never be saved. */
  cancel() {
    return this._turns.cancel();
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null, isPrivate = false) {
    return this._saving.saveCheck(answer, verdict, frame, isPrivate);
  }

  // A slow or late-failing write, counted under its Chat name (BoundedWriter's counters).
  _countWrite(counter) {
    const name = WRITE_COUNTS[counter] || counter;
    this.counts[name] = (this.counts[name] || 0) + 1;
  }

  /** The cached answer for a shared key, or null (kept for code that calls it; TurnCore looks up). */
  async _lookup(key, segment) {
    const looked = await this._core.lookUp(new ChatReading("").checkedAs(new Verdict(true, SHARED, [], null, {}, key, null, segment)));
    if (looked.objection) {
      this._report.count(looked.objection);
      return null;
    }
    return looked.hit.answer;
  }

  /** Registered fillers, by normalised trigger. */
  get fillers() {
    return this._fillers;
  }

  /** Send a monitoring event (never throws). */
  emit(event) {
    if (this.onEvent) eventHook(this, event);
  }

  /**
   * Whose system prompts this chat's is compared with: the same agent's on the same channel (a chat's
   * prompt never stands in for a voice call's).
   */
  promptKey() {
    const agent = this.agent || {};
    return [agent.tenant || (agent.client && agent.client.tenant) || null, agent.agentId || null, (this.checker && this.checker.channel) || null];
  }

  /** The agent answered `result`. Saves when allowed, updates the call state. Returns the outcome. */
  recordAnswer(result, answer, { mentions = [], task = null, private: isPrivate = false } = {}) {
    return this._core.record(new ChatAnswered(result, answer, mentions, task, isPrivate));
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



  /** The thread's memory for the app's store, between turns. No transcript is in it. */
  export() {
    return { version: 1, state: this.state.toDict(), next_turn: this._turns.nextTurn };
  }

  /** A session for the next turn of a thread saved with `export`. Damaged data starts fresh; never throws. */
  static restore(agent, understander, data, options = {}) {
    const session = new CallSession(agent, understander, options);
    data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
    session.state = CallState.fromDict(data.state);
    const next = Number.parseInt(data.next_turn, 10);
    if (Number.isFinite(next) && next >= 1) session._turns.nextTurn = next;
    return session;
  }

  stats() {
    return { ...this.counts };
  }


}

module.exports = { CallSession, TurnResult, FILLER, MODES, _masked: masked };
