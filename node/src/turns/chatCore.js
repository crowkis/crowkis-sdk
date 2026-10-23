"use strict";

const { ChatAnswer } = require("./chatAnswer.js");
const { ChatCachedAnswer, ChatHitCall, ChatHitTurn } = require("./chatCachedAnswer.js");
const { Hit } = require("./hit.js");
const { ChatTurn } = require("./chatTurn.js");
const { TurnResult } = require("./turnResult.js");
const { AGENT, FILLER, PERSONAL, SHARED, TOOLS, URGENT } = require("./routes.js");
const { Verdict } = require("../rules/ruleChecker.js");
const { TurnFrame } = require("../understanding/turnFrame.js");
const { identifiers, instructs, tellsAboutCaller, wordsOf } = require("../understanding/wordRules/index.js");
const { masked, names, norm, privateWords, told } = require("../understanding/chatDetails.js");

// Chat's counter for each way a lookup fails open.
const LOOKUP_COUNTS = { LookupDeadline: "lookup_timeouts", CacheUnavailable: "lookup_errors" };
const TIMEOUT = Symbol("timeout");
/** Resolve within `ms`, else TIMEOUT. The late promise keeps running and is ignored. */
function within(promiseOrValue, ms) {
  const work = Promise.resolve(promiseOrValue);
  if (ms === null || ms === undefined) return work;
  let timer;
  const late = new Promise((resolve) => { timer = setTimeout(() => resolve(TIMEOUT), ms); });
  return Promise.race([work, late]).finally(() => clearTimeout(timer));
}


/**
 * What ChatCore uses of the Chat session that hosts it (CallSession implements it): the chat's state,
 * counts, settings and hooks, read on every turn.
 * @typedef {object} ChatHost
 * @property {object} state @property {Object<string, number>} counts @property {string} mode
 * @property {object} agent @property {object} understander @property {object} checker @property {object|null} replay
 * @property {number} serveAbove @property {number|null} latencyBudgetMs @property {number|null} understandBudgetMs
 * @property {Function|null} onUrgent @property {string|null} urgentReply @property {Function|null} onTools
 * @property {string} instructions @property {Map<string, string>} fillers
 * @property {(event: object) => void} emit @property {() => any[]} promptKey
 */

/**
 * Template Method: the fixed steps of a Chat turn, beside the voice TurnCore (a single core for both
 * channels is P5's work). handle(): understand the turn, the rule checker and the checks once a
 * question would be shared, the urgent words, then a filler, the tools or the lookup inside the
 * budget. record(): pair the answer with its turn, the save rules, the write. The core owns its rule
 * chains, its lookup and its turns; `host` (ChatHost) is the session's state, counts, settings, hooks.
 */
class ChatCore {
  constructor(host, { cacheLookup, sharedQuestionRules, urgentWords, saveRules, hitRules, questionRecords, writer }) {
    this._host = host;
    this._cacheLookup = cacheLookup;
    this._hitRules = hitRules;
    this._questionRecords = questionRecords;
    this._writer = writer;
    this._sharedQuestionRules = sharedQuestionRules;
    this._urgentWords = urgentWords;
    this._saveRules = saveRules;
    this._nextId = 1;
    this._open = null;
    this._cancelled = new Set();
  }

  /** The number the next turn will get (kept with an exported thread). */
  get nextTurn() {
    return this._nextId;
  }

  set nextTurn(value) {
    this._nextId = value;
  }

  async handle(turn) {
    const tid = this._nextId++;
    const t = String(turn || "").split(/\s+/).filter(Boolean).join(" ");
    if (!t) return this._openTurn(new TurnResult(tid, AGENT, { reason: "empty" }));
    const filler = this._host.fillers.get(norm(t));
    if (filler !== undefined) {
      this._host.counts[FILLER] += 1;
      this._host.state.noteAgentReply(filler);
      return new TurnResult(tid, FILLER, { text: filler, needsModel: false, reason: "registered filler" });
    }
    if (this._host.mode === "off") {
      this._host.counts.sharing_off += 1;
      this._host.emit({ type: "turn", turnId: tid, route: AGENT, reasons: ["mode_off"], shared: false });
      return this._openTurn(new TurnResult(tid, AGENT, { reason: "sharing off" }));
    }

    // What the caller tells (an allergy, an age, a trip) must reach every later shared question,
    // this turn's included: noted before the check, in fixed code.
    const words = wordsOf(t);
    const aboutCaller = tellsAboutCaller(t);
    const frame = await this._understand(t);
    let named = new Set();
    if (aboutCaller) {
      let toldDetails;
      [named, toldDetails] = told(t, frame);
      this._host.state.noteStated(words.filter((w) => !named.has(w)).join(" "));
      this._host.state.noteDetails(toldDetails);
    }
    // On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah. What is the
    // refund policy?") is never in a shared question or answer.
    const said = [...new Set([...names(t, frame, aboutCaller), ...named])].sort();
    this._host.state.noteNames(said);
    this._host.state.noteIdentifiers(identifiers([t]));
    if (frame.language && instructs(t, words)) this._host.state.language = frame.language; // kept for the rest of the chat
    let verdict = this._host.checker.check(frame, t, this._host.state);
    const chatTurn = new ChatTurn(frame, t, this._host.state);
    if (verdict.shared) {
      const objection = this._sharedQuestionRules.firstObjection(chatTurn);
      if (objection) verdict = new Verdict(false, AGENT, [objection.reason]);
    }
    if (verdict.route !== URGENT && aboutCaller) {
      const objection = this._urgentWords.check(chatTurn);
      if (objection) verdict = new Verdict(false, objection.route, [objection.reason]); // never left to the model alone
    }
    this._host.state.apply(frame, { shared: verdict.shared });
    // A turn that is not telling a fact may still give a name ("hi i'm sarah"); a fact turn keeps
    // its words ("I'm allergic"), since the shared question must carry them.
    this._host.state.notePrivate([...(verdict.shared ? [] : privateWords(t, frame)), ...said]);
    this._host.counts[verdict.route] += 1;
    if (verdict.route === URGENT && this._host.onUrgent) {
      try { await this._host.onUrgent(t, frame); } catch { /* the hook must not take the call down */ }
    }
    if (verdict.route === URGENT && this._host.urgentReply) {
      this._host.state.noteAgentReply(this._host.urgentReply);
      return new TurnResult(tid, URGENT, { text: this._host.urgentReply, needsModel: false, frame, verdict, reason: "urgent script" });
    }
    if ((verdict.route === TOOLS || verdict.route === PERSONAL) && this._host.onTools) {
      let answered = null;
      try { answered = await this._host.onTools(t, frame); } catch { answered = null; /* a failing tool means the model answers */ }
      if (answered) {
        this._host.counts.tools_answered += 1;
        this._host.state.noteAgentReply(masked(answered));
        return new TurnResult(tid, verdict.route, { text: answered, needsModel: false, frame, verdict, reason: "answered by the business's tools" });
      }
    }
    const event = {
      type: "turn", turnId: tid, route: verdict.route, reasons: [...verdict.reasons], shared: verdict.shared,
      urgent: frame.urgent, kind: frame.kind, confidence: frame.confidence, question: verdict.question,
      key: verdict.key, questionType: verdict.shared ? frame.questionType : null,
    };
    if (verdict.route !== SHARED) {
      this._host.emit({ ...event, hit: false });
      return this._openTurn(new TurnResult(tid, verdict.route, { frame, verdict, reason: verdict.reasons.join(";") }));
    }
    if (this._host.replay) this._host.replay.remember(t, verdict.question, frame.questionType);
    const hit = await this._lookup(verdict.key, verdict.segment);
    if (hit !== null) {
      this._host.counts.hits += 1;
      this._host.state.noteAgentReply(hit);
      this._host.emit({ ...event, hit: true });
      return this._openTurn(new TurnResult(tid, SHARED, { text: hit, needsModel: false, frame, verdict, reason: "cache hit" }));
    }
    this._host.emit({ ...event, hit: false });
    const messages = [{ role: "user", content: verdict.question }];
    const notes = [];
    const attrs = Object.entries(verdict.attributes).sort();
    if (attrs.length) notes.push(`Answer for: ${attrs.map(([k, v]) => `${k}: ${v}`).join("; ")}.`);
    const language = this._host.state.language || frame.language;
    if (language) notes.push(`Reply in this language: ${language}.`);
    if (notes.length) messages.unshift({ role: "system", content: notes.join(" ") });
    return this._openTurn(new TurnResult(tid, SHARED, { frame, verdict, messages, reason: "cache miss" }));
  }

  /** `isPrivate`: the app built the answer from a tool's result, so it is never shared. Returns saved | slow_write | not_shared | refused:<why> | cancelled | stale. */
  async record(result, answer, mentions, task, isPrivate = false) {
    if (this._cancelled.has(result.turnId)) { this._host.counts.cancelled += 1; return "cancelled"; }
    if (!this._open || this._open.turnId !== result.turnId) return "stale";
    this._open = null;
    const kept = result.route === SHARED ? answer : masked(answer);
    this._host.state.noteAgentReply(kept, mentions, task);
    if (result.route !== SHARED || result.text !== null || !result.verdict) return "not_shared";
    const why = this.saveCheck(answer, result.verdict, result.frame, isPrivate);
    if (why) { this._host.counts.save_refused += 1; return "refused:" + why; }
    let slow;
    try {
      slow = await this._write(result.verdict, answer);
    } catch {
      this._host.counts.save_refused += 1;
      return "refused:write_failed";
    }
    if (slow) return slow.outcome;
    this._host.counts.saved += 1;
    this._questionRecords.keep(result.verdict.key, answer, result.verdict.ttl ?? null);
    return "saved";
  }

  /** Barge-in: the open turn is abandoned and its answer will never be saved. */
  cancel() {
    if (!this._open) return false;
    this._cancelled.add(this._open.turnId);
    this._open = null;
    return true;
  }

  /** Why an answer to a shared question must not be saved, or null. */
  saveCheck(answer, verdict, frame = null, isPrivate = false) {
    const chatAnswer = new ChatAnswer(String(answer || "").split(/\s+/).filter(Boolean).join(" "), verdict, frame,
      this._host.state, { instructions: this._host.instructions, promptKey: this._host.promptKey(), private: isPrivate });
    const objection = this._saveRules.firstObjection(chatAnswer);
    return objection ? objection.reason : null;
  }

  async _understand(t) {
    if (this._host.mode === "replay_only") {
      if (!this._host.replay) return TurnFrame.fromDict(null);
      this._host.counts.fallback_used += 1;
      return this._host.replay.understand(t, this._host.state);
    }
    try {
      // The model gets its own copy of the state: a late answer can never see a later turn's state.
      const frame = await within(this._host.understander.understand(t, this._host.state.clone()), this._host.understandBudgetMs);
      if (frame !== TIMEOUT) return frame || TurnFrame.fromDict(null);
      this._host.counts.understand_timeouts += 1;
    } catch {
      this._host.counts.understand_errors += 1;
    }
    if (this._host.replay && this._host.replay !== this._host.understander) {
      this._host.counts.fallback_used += 1;
      try { return this._host.replay.understand(t, this._host.state); } catch { /* fall through */ }
    }
    return TurnFrame.fromDict(null);
  }

  async _lookup(key, segment) {
    const ask = () => this._host.agent.ask(key, {
      serveAbove: this._host.serveAbove, cheapAbove: Math.min(0.6, this._host.serveAbove), ...(segment ? { segment } : {}),
    });
    const started = performance.now();
    const { hit, verdict } = await this._cacheLookup.find(ask, started, this._host.latencyBudgetMs);
    if (verdict) {
      this._host.counts[LOOKUP_COUNTS[verdict.rule]] += 1;
      return null;
    }
    if (!(hit && hit.route === "cache" && hit.answer)) return null;
    const call = new ChatHitCall(this._questionRecords, this._host.latencyBudgetMs);
    const objection = await this._hitRules.firstObjection(new ChatCachedAnswer(new ChatHitTurn(key, call), Hit.fromAgent(hit), started));
    if (objection) {
      // A refused hit is counted by the rule that refused it (v4 hit guards).
      this._host.counts[objection.rule] = (this._host.counts[objection.rule] || 0) + 1;
      return null;
    }
    return hit.answer;
  }

  // agent.learn(), waited for no longer than twice the latency budget (BoundedWriter, as voice); without a
  // budget it is waited for. null when written; else the BoundedWrite verdict.
  async _write(verdict, answer) {
    const learn = () => this._host.agent.learn(verdict.key, answer, {
      ttl: verdict.ttl ?? undefined, ...(verdict.segment ? { segment: verdict.segment } : {}),
    });
    const budget = this._host.latencyBudgetMs;
    if (budget === null || budget === undefined) {
      await learn();
      return null;
    }
    return this._writer.write(learn, 2 * budget);
  }

  _openTurn(result) {
    this._open = result;
    return result;
  }
}

module.exports = { ChatCore };
