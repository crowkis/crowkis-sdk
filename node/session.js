"use strict";

// CallSession: one call or chat thread on turn understanding v2.2. Mirrors crowkis/session.py.
//
//   understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check -> state update
//
// Routes: urgent (on_urgent hook first) | task | shared (lookup; a miss reads ONLY the question) |
// personal (agent + tools; shapes only phrase verified values) | tools | agent. Never cached
// except shared. Sits next to VoiceSession; existing users are unaffected.

const { CallState, IDENTITIES, wordDigest } = require("./callstate.js");
const {
  _isNonAnswer: isNonAnswer, _tellsAboutCaller: tellsAboutCaller, _instructs: instructs, _urgent: urgent,
  _wordsOf: wordsOf, _properNouns: properNouns,
} = require("./voice.js");
const { NOT_GENERAL_TYPES, TurnFrame } = require("./turn.js");
const { _FUNCTION: FUNCTION, _NUMWORDS: NUMWORDS, AGENT, PERSONAL, RuleChecker, SHARED, TASK, TOOLS, URGENT, Verdict } = require("./verify.js");

const FILLER = "filler";
// Phrases a name follows ("my name is sarah", "call me raj", "this is priya"). "I'm" is not one
// here: "I'm allergic" is a fact, not a name, and the shared question may carry it.
const NAME_LEADS = [["name", "is"], ["call", "me"], ["this", "is"]];
// "I'm Sarah" / "i am sarah, ...": the word after is a name when capitalised, or when the phrase ends with
// it; in a turn telling a fact only when "and" or a comma follows ("I'm diabetic." is the fact).
const SELF_INTRO = /\b[Ii](?:['\u2019]m| am|m)\s+(\p{L}+)(\s*(?:[,.!?;]|$)|\s+(?:and|from|here|calling|speaking)\b)?/gu;
// Words a person's name follows ("my colleague JOSE", "my son Arjun", "my teacher Mr Smith"): after
// my/our/his/her/their/your, the next capitalised word is a name whatever the model tagged it as.
const RELATIONS = new Set("colleague coworker friend son daughter wife husband partner mother mom mum father dad brother sister boss manager kid child baby grandma grandpa grandmother grandfather uncle aunt cousin neighbour neighbor roommate girlfriend boyfriend fiance fiancee teacher doctor client customer".split(" "));
const POSSESSIVE = new Set("my our his her their your s".split(" ")); // "s": "my wife's sister PRIYA"
const TITLES = new Set("mr mrs ms miss dr sir madam".split(" "));
const DAYS = "monday tuesday wednesday thursday friday saturday sunday".split(" ");
const CALENDAR = new Set([..."january february march april may june july august september october november december".split(" "),
  ...DAYS, ...DAYS.map((d) => d + "s")]);

// What names the caller in a turn: emails, long numbers, a name after "my name is", what the
// understanding model tagged as identifying, and, in a turn that is not telling a fact, any name it
// gives ("hi i'm sarah"). A fact turn keeps its words ("I'm allergic"): the question carries them.
function names(t, frame = null, fact = true) {
  const words = wordsOf(t);
  const found = new Set();
  const text = String(t || "");
  for (const named of [...(text.match(/\S+@\S+/g) || []), ...(text.match(/\p{Nd}(?:[\s-]?\p{Nd}){5,}/gu) || [])]) {
    for (const w of wordsOf(named)) found.add(w);
  }
  words.forEach((_, i) => {
    for (const lead of NAME_LEADS) {
      const end = i + lead.length;
      if (end < words.length && lead.every((w, k) => words[i + k] === w) && !FUNCTION.has(words[end])) found.add(words[end]);
    }
  });
  for (const x of frame ? frame.identifyingTexts : []) for (const w of wordsOf(x)) found.add(w);
  const tokens = text.match(/\p{L}+/gu) || [];
  for (let i = 1; i < tokens.length - 1; i++) {
    if (!RELATIONS.has(tokens[i].toLowerCase()) || !POSSESSIVE.has(tokens[i - 1].toLowerCase())) continue;
    const nxt = tokens[i + 1];
    // "Mr Smith", "O'Brien": the name is the word after the title or the one-letter part.
    const words = TITLES.has(nxt.toLowerCase()) || Array.from(nxt).length === 1 ? tokens.slice(i + 1, i + 3) : [nxt];
    for (const word of words) {
      const low = word.toLowerCase();
      if (word !== "I" && !FUNCTION.has(low) && !CALENDAR.has(low) && /[\p{Lu}\p{Lt}]/u.test(word)) found.add(low);
    }
  }
  for (const m of text.matchAll(SELF_INTRO)) {
    const word = m[1];
    const closer = m[2] === undefined ? null : m[2].trim();
    if (!FUNCTION.has(word.toLowerCase()) && (/^\p{Lu}/u.test(word) || (closer !== null && (!fact || closer === "," || closer === "and")))) {
      found.add(word.toLowerCase());
    }
  }
  return [...found].sort();
}

// A turn telling a fact, in two parts: what names the caller (never kept, never in a shared question)
// and the details a shared question must carry: a short number, a month or day, a place or thing the
// understanding model tagged ("3", "December", "Goa"). Any other capitalised word ("Priya") counts as
// a name, so a model that tags nothing keeps the chat private.
function told(t, frame) {
  const words = wordsOf(t);
  const named = new Set(names(t, frame));
  const tagged = new Set(frame.entities.filter((e) => !e.identifying && e.type !== "other_person").flatMap((e) => wordsOf(e.text)));
  const capitalised = new Set((String(t || "").match(/\p{L}+/gu) || [])
    .filter((w) => /^\p{Lu}/u.test(w) && w !== "I").map((w) => w.toLowerCase()).filter((w) => !FUNCTION.has(w)));
  const untagged = [...capitalised].filter((w) => !CALENDAR.has(w) && !tagged.has(w));
  for (const w of untagged) named.add(w);
  for (const w of words) if (/\p{Nd}/u.test(w) && w.length > 3) named.add(w);
  const details = new Set([...words.filter((w) => /\p{Nd}/u.test(w)), ...capitalised].filter((w) => !named.has(w)));
  for (const w of untagged) details.add(w);
  return [named, [...details].sort()];
}

// Everything in a turn that may identify the caller: its names, any number, any capitalised word.
// Broad on purpose; it only ever refuses a shared answer, so a wrong guess costs a hit.
function privateWords(t, frame = null) {
  const found = new Set([...wordsOf(t).filter((w) => /\p{Nd}/u.test(w)), ...properNouns(t), ...names(t, frame)]);
  return [...found].sort();
}
const MODES = ["full", "replay_only", "off"];
const TIMEOUT = Symbol("timeout");
const EMAIL = /\S+@\S+/;
const LONG_DIGITS = /\d(?:[\s-]?\d){5,}/;
// A reply to a private turn is kept between turns only to follow the conversation: names, emails
// and numbers in it are masked first (any word with a capital, a digit, or a letter of a script
// without case).
const REPLY_WORD = /\S+@\S+|[\p{L}\p{N}_]+/gu;
const MASKED = /[\p{Lu}\p{Lt}\p{Lo}\p{N}]/u;
const masked = (reply) => String(reply ?? "").replace(REPLY_WORD, (w) => (w.includes("@") || MASKED.test(w) ? "_" : w));
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
      urgentReply = null, onTools = null,
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
    this.setMode(mode);
    this.state = new CallState();
    this._fillers = new Map(Object.entries(fillers || {}).map(([k, v]) => [norm(k), v]));
    this._shapes = new Map();
    this._nextId = 1;
    this._open = null;
    this._cancelled = new Set();
    this.counts = Object.fromEntries([URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved",
      "save_refused", "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
      "cancelled", "sharing_off", "tools_answered"].map((k) => [k, 0]));
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

    // What the caller tells (an allergy, an age, a trip) must reach every later shared question,
    // this turn's included: noted before the check, in fixed code.
    const words = wordsOf(t);
    const aboutCaller = tellsAboutCaller(t);
    const frame = await this._understand(t);
    let named = new Set();
    if (aboutCaller) {
      let toldDetails;
      [named, toldDetails] = told(t, frame);
      this.state.noteStated(words.filter((w) => !named.has(w)).join(" "));
      this.state.noteDetails(toldDetails);
    }
    // On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah. What is the
    // refund policy?") is never in a shared question or answer.
    const said = [...new Set([...names(t, frame, aboutCaller), ...named])].sort();
    this.state.noteNames(said);
    if (frame.language && instructs(t, words)) this.state.language = frame.language; // kept for the rest of the chat
    let verdict = this.checker.check(frame, t, this.state);
    if (verdict.shared && this._carriesPrivateWord(verdict.question)) verdict = new Verdict(false, AGENT, ["V5_private_word"]);
    else if (verdict.shared && this._dropsADetail(verdict.question)) verdict = new Verdict(false, AGENT, ["V7_lost_detail"]);
    else if (verdict.shared && this._namesSomeoneUntagged(verdict.question, frame)) verdict = new Verdict(false, AGENT, ["V5_untagged_name"]);
    if (verdict.route !== URGENT && aboutCaller && urgent(words)) {
      verdict = new Verdict(false, URGENT, ["V1_urgent_fixed"]); // never left to the model alone
    }
    this.state.apply(frame, { shared: verdict.shared });
    // A turn that is not telling a fact may still give a name ("hi i'm sarah"); a fact turn keeps
    // its words ("I'm allergic"), since the shared question must carry them.
    this.state.notePrivate([...(verdict.shared ? [] : privateWords(t, frame)), ...said]);
    this.counts[verdict.route] += 1;
    if (verdict.route === URGENT && this.onUrgent) {
      try { await this.onUrgent(t, frame); } catch { /* the hook must not take the call down */ }
    }
    if (verdict.route === URGENT && this.urgentReply) {
      this.state.noteAgentReply(this.urgentReply);
      return new TurnResult(tid, URGENT, { text: this.urgentReply, needsModel: false, frame, verdict, reason: "urgent script" });
    }
    if ((verdict.route === TOOLS || verdict.route === PERSONAL) && this.onTools) {
      let answered = null;
      try { answered = await this.onTools(t, frame); } catch { answered = null; /* a failing tool means the model answers */ }
      if (answered) {
        this.counts.tools_answered += 1;
        this.state.noteAgentReply(masked(answered));
        return new TurnResult(tid, verdict.route, { text: answered, needsModel: false, frame, verdict, reason: "answered by the business's tools" });
      }
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
    const hit = await this._lookup(verdict.key, verdict.segment);
    if (hit !== null) {
      this.counts.hits += 1;
      this.state.noteAgentReply(hit);
      this._emit({ ...event, hit: true });
      return this._openTurn(new TurnResult(tid, SHARED, { text: hit, needsModel: false, frame, verdict, reason: "cache hit" }));
    }
    this._emit({ ...event, hit: false });
    const messages = [{ role: "user", content: verdict.question }];
    const notes = [];
    const attrs = Object.entries(verdict.attributes).sort();
    if (attrs.length) notes.push(`Answer for: ${attrs.map(([k, v]) => `${k}: ${v}`).join("; ")}.`);
    const language = this.state.language || frame.language;
    if (language) notes.push(`Reply in this language: ${language}.`);
    if (notes.length) messages.unshift({ role: "system", content: notes.join(" ") });
    return this._openTurn(new TurnResult(tid, SHARED, { frame, verdict, messages, reason: "cache miss" }));
  }

  /** The agent answered `result`. Saves when allowed, updates the call state. Returns the outcome. */
  /** A word in the shared question with a capital ("Priya", "PRIYA", "McKenzie"), or in a script without
   * capitals, that the understanding model did not tag as a place, thing or topic, that is no month or day,
   * and that no earlier shared turn of this chat said. Fixed code cannot tell "Priya" from "France" or
   * "SSO"; the model's tag can (it is asked to tag every one). */
  _namesSomeoneUntagged(question, frame) {
    const allowed = new Set(frame.entities.filter((e) => !e.identifying && !NOT_GENERAL_TYPES.has(e.type)).flatMap((e) => wordsOf(e.text)));
    for (const w of [...CALENDAR, ...wordsOf(this.state.activeQuestion || ""), ...wordsOf(this.state.lastReply)]) allowed.add(w);
    const flagged = new Set();
    (String(question || "").match(/\p{L}+/gu) || []).forEach((word, i) => {
      const low = word.toLowerCase();
      if (word === "I" || (i === 0 && FUNCTION.has(low))) return; // "What ...", "How ..."
      if (/[\p{Lu}\p{Lt}\p{Lo}]/u.test(word)) flagged.add(low);
    });
    return [...flagged].some((w) => !allowed.has(w) && !this.state.details.includes(wordDigest(w)));
  }

  /** A place, month or number the caller told ("Goa in December") is missing from the question. */
  _dropsADetail(question) {
    const words = wordsOf(question || "");
    const asked = new Set([...words.map(wordDigest), ...words.map((w) => wordDigest(NUMWORDS[w] || w))]); // "three" is "3"
    return this.state.details.some((d) => !asked.has(d));
  }

  /** The shared question says what named the caller earlier ("for sarah"). */
  _carriesPrivateWord(question) {
    return wordsOf(question || "").some((w) => this.state.isName(w));
  }

  async recordAnswer(result, answer, { mentions = [], task = null } = {}) {
    const outcome = await this._record(result, answer, mentions, task);
    this._emit({ type: "answer", turnId: result.turnId, route: result.route, outcome, key: result.verdict ? result.verdict.key : null });
    return outcome;
  }

  async _record(result, answer, mentions, task) {
    if (this._cancelled.has(result.turnId)) { this.counts.cancelled += 1; return "cancelled"; }
    if (!this._open || this._open.turnId !== result.turnId) return "stale";
    this._open = null;
    const kept = result.route === SHARED ? answer : masked(answer);
    this.state.noteAgentReply(kept, mentions, task);
    if (result.route !== SHARED || result.text !== null || !result.verdict) return "not_shared";
    const why = this.saveCheck(answer, result.verdict, result.frame);
    if (why) { this.counts.save_refused += 1; return "refused:" + why; }
    try {
      await this.agent.learn(result.verdict.key, answer, {
        ttl: result.verdict.ttl ?? undefined, ...(result.verdict.segment ? { segment: result.verdict.segment } : {}),
      });
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
      const pattern = attr.value ? new RegExp(`\\b${escapeRe(attr.value)}\\b`, "i") : null;
      // A value the question itself says ("the capital of France") is part of what was asked.
      if (!(name in verdict.attributes) && pattern && pattern.test(t) && !pattern.test(verdict.question || "")) {
        return "attribute_not_in_key";
      }
    }
    // A word that identified the caller in a turn that was not shared ("Sarah", "55512") is never
    // in a shared answer, unless the shared question itself has it.
    const asked = new Set(wordsOf(verdict.question || ""));
    if (wordsOf(t).some((w) => !asked.has(w) && this.state.isPrivate(w))) return "private_word";
    return null;
  }

  /** The thread's memory for the app's store, between turns. No transcript is in it. */
  export() {
    return { version: 1, state: this.state.toDict(), next_turn: this._nextId };
  }

  /** A session for the next turn of a thread saved with `export`. Damaged data starts fresh; never throws. */
  static restore(agent, understander, data, options = {}) {
    const session = new CallSession(agent, understander, options);
    data = data && typeof data === "object" && !Array.isArray(data) ? data : {};
    session.state = CallState.fromDict(data.state);
    const next = Number.parseInt(data.next_turn, 10);
    if (Number.isFinite(next) && next >= 1) session._nextId = next;
    return session;
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

  async _lookup(key, segment) {
    try {
      const hit = await within(this.agent.ask(key, {
        serveAbove: this.serveAbove, cheapAbove: Math.min(0.6, this.serveAbove), ...(segment ? { segment } : {}),
      }),
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

module.exports = { CallSession, TurnResult, FILLER, MODES, _masked: masked };
