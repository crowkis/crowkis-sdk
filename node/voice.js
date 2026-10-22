"use strict";

const crypto = require("node:crypto");
const { Agent, voiceAddonMissing, _storeLater: storeLater } = require("./agent.js");
const { CrowkisClient } = require("./index.js");
const { RuleChain } = require("./src/rules/chain.js");
const { RuleSet } = require("./src/rules/ruleSet.js");
const { CachedAnswer } = require("./src/turns/cachedAnswer.js");
const { ModelAnswer } = require("./src/turns/modelAnswer.js");
const { SessionCall } = require("./src/turns/sessionCall.js");
const { BoundedWriter } = require("./src/runtime/boundedWriter.js");
const { CacheLookup } = require("./src/runtime/cacheLookup.js");
const { LATE, within } = require("./src/runtime/deadline.js");
const { Verdict } = require("./src/turns/verdict.js");
const { VoiceTurn } = require("./src/turns/voiceTurn.js");
const { NoRewrite } = require("./src/understanding/noRewrite.js");
const { WordRuleClassifier } = require("./src/understanding/wordRuleClassifier.js");

// The server takes at most this per count in one report.
const REPORT_MAX = 1000000;

const {
  TRIM,
  TRIM_EDGES,
  WORDS,
  SLOT,
  CONTEXT_BOUND_THRESHOLD,
  UNSPEAKABLE,
  COMMITMENTS,
  firstWords,
  hasPhrase,
  speakable,
  POSSESSIVES,
  OTHER_POSSESSIVES,
  OWNERS,
  FIRST_PERSON,
  PROCEDURAL,
  PROCEDURAL_BY_FIRST,
  MAIN_THINGS,
  REQUEST_VERBS,
  OWNER_PREPOSITIONS,
  STATE_LEADS,
  CONNECTIVES,
  CONNECTIVE_PAIRS,
  ELLIPSIS_LEADS,
  CLAUSE_MARKERS,
  FOLLOW_UP_PHRASES,
  FOLLOW_UP_PHRASES_BY_FIRST,
  FOLLOW_UP_ENDINGS,
  ANAPHOR_PHRASES,
  ANAPHORS,
  DEMONSTRATIVES,
  FUNCTION_WORDS,
  BARE,
  NON_REFERENTS,
  PRONOUN_FOLLOWERS,
  CALLER_KINDS,
  CALLER_LEADS,
  SELF_PHRASES,
  SELF_PHRASES_BY_FIRST,
  describesCaller,
  normalise,
  wordsOf,
  QUESTIONS_KEPT,
  FRAMING_WORDS,
  QUESTION_TTL,
  stem,
  contentWords,
  differentSpecifics,
  splitPlain,
  contains,
  ownedRecordAt,
  procedural,
  requests,
  isStateInterrogative,
  OWNED_THINGS,
  STATE_WORDS,
  GREETINGS,
  INTRO_AFTER_GREETING,
  SPOKEN_DIGITS,
  DIGIT_REPEATS,
  EMAIL_ENDINGS,
  ACTION_VERBS,
  ACTION_OBJECTS,
  ACTION_LEADS,
  ACTION_LEADS_BY_FIRST,
  DISCOURSE,
  REPLY_LEADS,
  SOFT_REPLY_LEADS,
  QUESTION_LEADS,
  WH_WORDS,
  STATEMENT_SUBJECTS,
  STATEMENT_VERBS,
  SINGLE_WORDS,
  SENSITIVE,
  CRISIS_PHRASES,
  CRISIS_PHRASES_BY_FIRST,
  EMERGENCY_STEMS,
  EMERGENCY_PHRASES,
  EMERGENCY_PHRASES_BY_FIRST,
  WANTS,
  DYING,
  LIVING,
  NEGATIONS,
  HARMS,
  REFLEXIVES,
  SUBSTANCES,
  INGESTED,
  INJURIES,
  EVENT_MARKERS,
  urgent,
  NEVER_PHRASES,
  NEVER_PHRASES_BY_FIRST,
  STORY_PHRASES,
  STORY_PHRASES_BY_FIRST,
  PAST_TENSE,
  NOT_A_STORY,
  STORY_FILLERS,
  DIGITS,
  SPACED_DIGITS,
  EMAIL,
  IPV4,
  CLAUSES,
  LETTER,
  MAX_TURN_CHARS,
  MATTERS,
  DISCLOSURE_LEADS,
  DISCLOSURE_LEADS_BY_FIRST,
  STATES,
  SELF_MARKERS,
  KINDS_OF_PEOPLE,
  RELATIONS,
  THIRD_PERSON,
  SOMEONE,
  FOLLOW_UP_WORDS,
  URGENT,
  ID_WORDS,
  AMOUNT_WORDS,
  NUMBER_WORDS,
  MONTHS,
  ORDINALS,
  DATE,
  STREET_WORDS,
  HASH_NUMBER,
  CODE,
  QUANTITIES,
  BARE_NUMBER,
  ENDS_IN,
  UNIT_WORDS,
  DECIMAL,
  HAS_DECIMAL,
  ALNUM,
  hasDigit,
  amount,
  anyIn,
  isStreetWord,
  isNumberNear,
  isNumberWord,
  identifies,
  INTRO_LEADS,
  INTRODUCTIONS,
  INTRODUCTIONS_BY_FIRST,
  NAME_ARTICLES,
  CLAUSE_OPENERS,
  NAME_SLOTS,
  TITLES,
  AUXILIARIES,
  PERSON_VERBS,
  NAME_VERBS,
  POSTPOSITIONS,
  PLACE_PREPOSITIONS,
  PERSONAL_MATTERS,
  PERSON_CUES,
  ASK_FOR,
  ASK_FOR_BY_FIRST,
  ROLES,
  POSSESSIVE_NAME,
  COMMON_CAPITALS,
  KNOWN_WORDS,
  unknown,
  namesSomeone,
  charBefore,
  isUpper,
  capitalised,
  capitalisedName,
  discloses,
  carriesDetail,
  tooLong,
  startsWith,
  unreadable,
  readsOutDigits,
  commands,
  asserts,
  tellsOwnStory,
  neverShare,
  DIAGNOSIS_LEADS,
  DIAGNOSIS_LEADS_BY_FIRST,
  ARTICLES,
  HAVE_OBJECTS,
  diagnosis,
  sensitiveSelf,
  ASKING_WORDS,
  ASKING_LEADS,
  FIRST_CLAUSE,
  NEUTRAL,
  asks,
  isPersonal,
  lookupOnly,
  hasAntecedent,
  pointsForward,
  hasBareAnaphor,
  isContextDependent,
  slotNames,
  fill,
  MIN_ABSTRACT_LEN,
  escapeRegExp,
  abstract,
  flatten,
  leaks,
  PII_PLACEHOLDER,
  ID_TOKEN,
  YEAR,
  identifiers,
  repeatsIdentifier,
  privateChain,
  carriesCallContext,
  STEERING,
  STEERING_BY_FIRST,
  NAMING,
  PERSON_WORDS,
  RECORD_LABELS,
  BUSINESS_WORDS,
  LABEL_WORDS,
  SENTENCE_END,
  NUMBER_RUN,
  EMAIL_ADDRESS,
  LABEL,
  isDecimalWord,
  startsUpper,
  numbersOf,
  labelOf,
  aboutAPerson,
  valueWords,
  promptDetails,
  BASELINES,
  BASELINES_MAX,
  resetPromptBaselines,
  callerDetails,
  sameNumber,
  repeatsPromptDetails,
  properNouns,
  identifying,
  BIRTH_WORDS,
  SELF_STATES,
  HAVING,
  MY,
  SELF_ATTRIBUTES,
  PLAN_VERBS,
  NOT_AGE_UNITS,
  AGE_WORDS,
  CHANGE_VERBS,
  TREATMENTS,
  ARTICLE_FILLERS,
  GENERIC_ROLES,
  HAVE_NOT,
  PLANS,
  LIFE_WORDS,
  NOT_TOLD,
  TELLING_VERBS,
  INSTRUCTIONS,
  INSTRUCTIONS_ANYWHERE_BY_FIRST,
  NOT_AN_OBJECT,
  NEEDS_AN_OBJECT,
  REQUEST_OPENERS,
  clauseStarts,
  instructs,
  leadsAt,
  statesSelf,
  actsOnOwn,
  describesSelf,
  setsContext,
  tellsAboutCaller,
  tellsFacts,
  NON_ANSWER_PHRASES,
  REDIRECTS,
  SOFTENERS,
  SENTENCE,
  DANGLING,
  TRAILING_FILLERS,
  TAKES_IN_ON,
  unfinished,
  isNonAnswer,
  answersAfterBut,
} = require("./src/understanding/wordRules/index.js");

function questionKey(tenant, answer) {
  const trimmed = String(answer).replace(/^[ \t\r\n]+|[ \t\r\n]+$/g, ""); // as Python's strip(" \t\r\n")
  const digest = crypto.createHash("sha256").update(trimmed, "utf8").digest("hex").slice(0, 32);
  return `crowkis:question:${tenant || "default"}:${digest}`;
}

const tenantOf = (agent) => (agent && (agent.tenant || (agent.client && agent.client.tenant))) || null;


// Writes a turn stopped waiting for (past twice the latency budget), finishing in the background.
// At most WRITES_MAX wait at once: past it (a hung server) a new answer is not written at all.
let WRITES_MAX = 256;
const pendingWrites = new Set();

/** For tests: every write handed to the background has finished. */
// Question records being written in the background (not capped like answer writes).
const pendingRecords = new Set();

async function waitForWrites() {
  await Promise.allSettled([...pendingWrites, ...pendingRecords]);
}

// For tests: a smaller cap; returns a function that puts the old one back.
function setWritesMax(max) {
  const old = WRITES_MAX;
  WRITES_MAX = max;
  return () => { WRITES_MAX = old; };
}

// How many follow-ups back a turn may lean on before it is treated as unresolvable.
const CHAIN_LIMIT = 6;

// How many already-checked caller turns a session remembers for _heard() (past it, a turn is checked again).
const HEARD_MAX = 2048;
// What _recordModelTurn did with an answer; the two that put it in the shared cache.
const STORED = new Set(["saved", "template"]);

class TurnDecision {
  constructor(action, { text = null, audio = null, confidence = 0, reason = "", rule = null } = {}) {
    this.action = action;
    this.text = text;
    this.audio = audio;
    this.confidence = confidence;
    this.reason = reason;
    // The rule behind the action (null for a confident hit), and after record() the rule
    // that kept the answer out of the cache (null when it was stored). Names are the v4
    // rule names, so a decision can be traced to the one check that made it.
    this.rule = rule;
    this.saveRule = null;
    // For a model turn: what the model must read, and whether its answer is shared.
    // null means "the whole call", and then the answer is never shared.
    this.messages = null;
    this.cacheable = false;
    // Which turn of the call this is; an answer recorded for an older turn is dropped.
    this.turn = 0;
    // After answer(): whether the model's answer was stored, and if not, why.
    this.stored = false;
    this.notStored = "";
    // Not enumerable: read through `empty`, never set by callers or copied out with the decision.
    Object.defineProperty(this, "_empty", { value: false, writable: true, enumerable: false });
    Object.defineProperty(this, "_audioShareable", { value: false, writable: true, enumerable: false });
    // Set by decide(): the session that made it (a WeakRef, so a kept decision never
    // keeps a call alive) and, for a model turn, what the caller said, so record()
    // takes a decision only from its own session, and only once. Not enumerable, so a
    // logged or serialised decision never carries them; the caller's words are dropped
    // once recorded.
    Object.defineProperty(this, "_session", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_said", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_recorded", { value: false, writable: true, enumerable: false });
  }

  /** Whether the spoken audio of this answer may go to the shared audio cache: not for an answer filled with this caller's values. */
  get audioShareable() {
    return this._audioShareable;
  }

  get servedFromCache() {
    return this.action === "serve";
  }

  get servedFromFiller() {
    return this.action === "filler";
  }

  get needsModel() {
    return this.action === "infer";
  }

  /** After answer(): the model was asked and said nothing (the action stays "infer"); retry, or speak a fallback. */
  get empty() {
    return this._empty;
  }

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
  }
}

// What VoiceSession.respond() resolves to: read it with `for await` for the text to
// speak, piece by piece as the model writes it. `decision` is ready at once, before the
// first piece: decision.servedFromCache and decision.audio say whether a cached answer
// (and its audio) can be played instead of running the TTS. A response is read once.
class VoiceResponse {
  constructor(session, decision, callerSaid, llm, system, keep) {
    this.decision = decision;
    for (const [name, value] of Object.entries({ session, callerSaid, llm, system, keep })) {
      Object.defineProperty(this, `_${name}`, { value, enumerable: false });
    }
    Object.defineProperty(this, "_pieces", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_closed", { value: false, writable: true, enumerable: false });
  }

  [Symbol.asyncIterator]() {
    if (this._pieces) throw new Error("a VoiceResponse is read once");
    this._pieces = this._run();
    return this._pieces;
  }

  // Stop early: the model's stream is closed and nothing is stored.
  async close() {
    this._closed = true;
    if (!this._pieces) {
      this._pieces = (async function* () {})();
      return;
    }
    await this._pieces.return();
  }

  // The caller talked over this turn, a newer turn was decided, or the app recorded the
  // turn itself: speak no more of this answer.
  _stopped() {
    return this.decision._recorded || this._session._movedOn(this.decision);
  }

  async *_run() {
    const session = this._session;
    const decision = this.decision;
    if (!decision.needsModel) {
      if (decision.text) yield decision.text;
      return;
    }
    if (this._stopped()) {
      // Talked over before a word was read: never call the model.
      session._interrupted(decision, "");
      return;
    }
    // As answer() does, so a subclass whose decide() returns its own decision works.
    decision._said = this._callerSaid;
    let messages = decision.messages || [...session.injections(), { role: "user", content: this._callerSaid }];
    if (this._system) messages = [{ role: "system", content: this._system }, ...messages];
    let source = await this._llm(messages);
    if (typeof source === "string" || source instanceof String) source = [String(source)];
    let upstream;
    if (source && typeof source[Symbol.asyncIterator] === "function") upstream = source[Symbol.asyncIterator]();
    else if (source && typeof source[Symbol.iterator] === "function") upstream = source[Symbol.iterator]();
    else throw new TypeError("respond() expects the model to give text: a string, or an (async) iterable of text pieces");
    const parts = [];
    let ended = false;
    let movedOn = false;
    try {
      for (;;) {
        const { value: piece, done } = await upstream.next();
        if (done) {
          ended = true;
          break;
        }
        if (piece === null || piece === undefined) continue;
        if (typeof piece !== "string") {
          throw new TypeError(
            `respond() expects the model to give text pieces (strings), got ${typeof piece}; map each chunk to its text first`
          );
        }
        if (this._stopped()) {
          movedOn = true;
          break;
        }
        parts.push(piece);
        if (piece) yield piece;
      }
    } finally {
      if (!ended && typeof upstream.return === "function") {
        try {
          await upstream.return();
        } catch {
          // the model's stream failed to close; nothing of it is kept either way
        }
      }
      if (movedOn) {
        session._interrupted(decision, parts.join(""));
      } else if (ended && !this._closed && !decision._recorded) {
        // A full answer is recorded under answer()'s rules.
        await session._recordDecision(decision, parts.join(""), this._keep, this._system);
      }
    }
  }
}

class VoiceSession {
  constructor(
    agent,
    {
      voice,
      serveAbove = 0.92,
      minWords = 3,
      synthesise,
      ttl,
      latencyBudgetMs,
      fillers,
      values,
      commitments = "exact",
      shortTurns = false,
      shareTemplates = false,
      language = "und",
      speed = "1",
      audioFormat = "default",
      bytesPerSecond,
    } = {}
  ) {
    if (!(serveAbove >= 0 && serveAbove <= 1)) {
      throw new Error(`serveAbove must be in 0..1, got ${serveAbove}`);
    }
    if (!Object.prototype.hasOwnProperty.call(COMMITMENTS, commitments)) {
      throw new Error(
        `commitments must be one of ${Object.keys(COMMITMENTS).sort().join(", ")}, got ${commitments}`
      );
    }
    if (latencyBudgetMs !== undefined && latencyBudgetMs !== null && !(latencyBudgetMs > 0)) {
      throw new Error(`latencyBudgetMs must be positive, got ${latencyBudgetMs}`);
    }
    const voiceId = typeof voice === "string" ? voice.trim() : "";
    if (!voiceId) {
      throw new Error(
        "VoiceSession requires a voice id. Cached audio is only reusable for the " +
          "voice that produced it, and switching voices mid-call is audible"
      );
    }
    this.agent = agent;
    this.voice = voiceId;
    // What changes the sound besides the voice: a clip is reused only when all match (Voice add-on).
    this.language = language;
    this.speed = speed;
    this.audioFormat = audioFormat;
    this.bytesPerSecond = bytesPerSecond;
    this._reported = {};
    this.serveAbove = serveAbove;
    this.minWords = minWords;
    this.synthesise = synthesise;
    this.ttl = ttl;
    this.latencyBudgetMs = latencyBudgetMs;
    this.commitments = commitments;
    this.shortTurns = Boolean(shortTurns);
    // Off by default: a template is cut from an answer the model wrote with the whole
    // call in view, so what is left outside its slots can hold what the caller said.
    this.shareTemplates = Boolean(shareTemplates);
    this.values = Object.create(null);
    this.transcript = [];
    this.served = 0;
    this.inferred = 0;
    this.filled = 0;
    this.refusedShort = 0;
    this.refusedPrivate = 0;
    this.uncacheablePersonal = 0;
    this.overBudget = 0;
    this.bargeIns = 0;
    this.lookupErrors = 0;
    this.learnErrors = 0;
    // Writes the turn stopped waiting for at the latency budget (they finish in the background).
    this.slowWrites = 0;
    // Hits refused because the stored answer was saved for a different question.
    this.differentQuestion = 0;
    this.notShareable = 0;
    this.heldCommitments = 0;
    this.unspeakable = 0;
    this.emptyAnswers = 0;
    this.audioUnavailable = 0;
    // The question the latest stored answer was stored under.
    this._lastStored = null;
    this._fillers = new Map();
    this._open = false;
    this._cancelled = false;
    this._turnMark = 0;
    this._turn = 0;
    // [turn, whether that turn's answer may be shared]: read with the turn it belongs
    // to, so a decide() that finishes after a newer one never lends the newer turn its
    // flag (two decide() calls in flight at once). Same as Python's _shareable.
    this._shareable = [0, false];
    // Set once the caller tells the call something a later answer may depend on;
    // from then on nothing in this call is looked up or shared.
    this._tainted = false;
    // The checks of the three SDK stages, read through this call's view of the session.
    this._rules = RuleSet.voice();
    // How a turn is understood: the word rules, and no rewrite, until an understander is plugged in.
    this._classifier = new WordRuleClassifier();
    this._rewriter = new NoRewrite();
    this._call = new SessionCall(this);
    this._ruleCounts = new Map();
    // Writes wait at most twice the budget; the cap is read when a write starts.
    this._writer = new BoundedWriter(pendingWrites, () => WRITES_MAX, (name) => { this[name] += 1; },
      (message) => console.warn(message));
    // Lookups run inside the budget the call has when it looks up.
    this._cacheLookup = new CacheLookup();
    // Caller turns _heard() has already checked (history is re-read every turn).
    this._heardTexts = new Set();
    if (values) this.setValues(values);
    if (fillers) this.registerFillers(fillers);
  }

  setValues(values = {}) {
    for (const [name, value] of Object.entries(values)) {
      if (value === null || value === undefined) delete this.values[name];
      else this.values[name] = String(value);
    }
  }

  registerFiller(trigger, response) {
    const key = normalise(trigger);
    if (!key) throw new Error("a filler trigger must contain something to match on");
    if (!(typeof response === "string" && response.trim())) {
      throw new Error("a filler response must not be empty");
    }
    this._fillers.set(key, response);
  }

  registerFillers(pairs = {}) {
    for (const [trigger, response] of Object.entries(pairs)) {
      this.registerFiller(trigger, response);
    }
  }

  async decide(callerSaid) {
    this._turn += 1;
    const turn = this._turn;
    const decision = await this._decide(callerSaid);
    decision.turn = turn;
    decision._session = new WeakRef(this);
    if (decision.needsModel) {
      decision._said = callerSaid;
      [decision.messages, decision.cacheable] = this._modelMessages(callerSaid);
    }
    // A newer turn's flag is never overwritten by an older one.
    if (turn === this._turn) this._shareable = [turn, decision.cacheable];
    return decision;
  }

  // What the model should read to answer this turn, and whether that answer may
  // be cached. A shared answer is only safe when the model saw nothing but the
  // cache key: the question, and for a follow-up the questions it leans on.
  // Personal turns, and follow-ups to one, get the whole call and are never shared.
  _modelMessages(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (
      this._tainted || text.split(/\s+/).filter(Boolean).length < this.minWords || isPersonal(text) || lookupOnly(text) ||
      this._afterUrgent(text) || unfinished(text)
    ) {
      return [null, false];
    }
    if (!isContextDependent(text)) {
      // "Twelve years old.": a turn that neither asks nor requests anything is an
      // answer about the caller, never stored on its own.
      if (!asks(text)) return [null, false];
      return [[{ role: "user", content: callerSaid }], true];
    }
    const chain = this._chain();
    if (chain === null || privateChain(chain, this.minWords)) return [null, false];
    return [[...chain, callerSaid].map((turn) => ({ role: "user", content: turn })), true];
  }

  async _decide(callerSaid) {
    this._turnMark = this.transcript.length;
    this._open = true;
    this._cancelled = false;

    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    const reading = this._classifier.classify(text);
    const turn = new VoiceTurn(callerSaid, this._call, reading, this._rewriter.rewrite(text, reading));
    let verdict = this._rules.beforeFiller.firstObjection(turn);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict);

    const filler = this._fillers.get(normalise(turn.text));
    if (filler !== undefined) {
      this.filled += 1;
      const decision = new TurnDecision("filler", {
        text: filler,
        audio: await this._voiced(filler),
        confidence: 1,
        reason: "registered filler, answered without a lookup or a model",
        rule: "RegisteredFiller",
      });
      decision._audioShareable = true;
      return decision;
    }

    verdict = this._rules.question.firstObjection(turn);

    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict);

    const started = performance.now();
    const { hit, verdict: lookupVerdict } = await this._lookup(turn, started);
    if (lookupVerdict) return this._infer(lookupVerdict);

    const cached = new CachedAnswer(turn, hit, started);
    verdict = this._rules.hit.firstObjection(cached);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._infer(verdict, hit.confidence);

    this.served += 1;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: cached.answer });
    const decision = new TurnDecision("serve", {
      text: cached.answer,
      audio: await this._voiced(cached.answer, { cacheable: !turn.isPersonal }),
      confidence: hit.confidence,
      reason: "confident cache hit",
    });
    decision._audioShareable = !turn.isPersonal;
    return decision;
  }

  // The cache's hit for a turn, within the latency budget, or a Verdict when the cache was too
  // slow or could not be reached (the model answers then).
  async _lookup(turn, started) {
    const ask = () => this.agent.ask(turn.key, {
      serveAbove: this.serveAbove,
      cheapAbove: Math.min(0.6, this.serveAbove),
      template: turn.isPersonal,
      threshold: turn.isContextDependent || turn.isShort ? CONTEXT_BOUND_THRESHOLD : undefined,
    });
    return this._cacheLookup.find(ask, started, this.latencyBudgetMs);
  }

  // The model answers this turn: `verdict` says which rule decided so, and why.
  _infer(verdict, confidence = 0) {
    this._countVerdict(verdict);
    this._ruleCounts.set(verdict.rule, (this._ruleCounts.get(verdict.rule) || 0) + 1);
    return new TurnDecision("infer", { confidence, reason: verdict.reason, rule: verdict.rule });
  }

  _countVerdict(verdict) {
    for (const name of verdict.counts) this[name] += 1;
  }

  /**
   * Whether the server judges what it caches, asked inside this call's budget:
   * a slow answer is a no for this turn, and is there for the next.
   */
  async _engineVouches() {
    const asked = this.agent.decides();
    if (this.latencyBudgetMs === undefined || this.latencyBudgetMs === null) return asked;
    const answer = await within(this.latencyBudgetMs, asked);
    return answer === LATE ? false : answer;
  }

  cancel() {
    if (!this._open) return false;
    this._open = false;
    this._cancelled = true;
    this.bargeIns += 1;
    this.transcript.length = this._turnMark;
    return true;
  }

  // Run one caller turn end to end: cache, or the model, then remember the answer.
  // `llm` is called with exactly the messages Crowkis chose for this turn: the
  // question alone (or with the question before it) when the answer may be shared,
  // the whole call when it may not. `system` is the app's own instructions, the
  // same for every caller, and is put first. The returned decision carries the
  // text to speak, from the cache or from the model, and `stored` / `notStored`
  // say whether the model's answer was cached and why not. A model that says
  // nothing sets `empty`: retry, or speak a fallback.
  async answer(callerSaid, llm, { system = null } = {}) {
    const decision = await this.decide(callerSaid);
    if (!decision.needsModel) return decision;
    let messages = decision.messages || [...this.injections(), { role: "user", content: callerSaid }];
    if (system) messages = [{ role: "system", content: system }, ...messages];
    // Straight to the recording step: answer() made this decision itself, so a
    // subclass whose decide() returns its own decision object keeps working.
    decision._said = callerSaid;
    return this._recordDecision(decision, await llm(messages), false, system);
  }

  // Save the answer to a turn you sent to your own model: decide(), then call the
  // model with decision.messages, then record(decision, its answer).
  //
  // The same rules as answer() decide what happens to it: shared with other callers
  // only when decide() said it may be (decision.cacheable), kept to this call
  // otherwise, and dropped when the caller talked over it (cancel()) or a newer turn
  // was decided since. `private: true` keeps a shareable answer to this call, e.g. one
  // built from a tool's result. Never rejects for the server: a refused write is
  // reported, not thrown.
  //
  // Resolves to `decision` with `text` set to the answer and stored / notStored /
  // empty filled in, as answer() does. Rejects for a decision this session did not
  // make, one that did not need the model (served from the cache or a filler), or one
  // already recorded.
  async record(decision, answer, { private: keep = false, system = null } = {}) {
    if (!(decision instanceof TurnDecision)) {
      throw new Error("record() takes the TurnDecision decide() returned");
    }
    if (decision._recorded) throw new Error("record() got a decision that was already recorded");
    const owner = decision._session ? decision._session.deref() : undefined;
    if (owner !== this) {
      throw new Error(
        decision._session
          ? "record() got a decision from another session: each call's answers are recorded in the session that decided them"
          : "record() takes a decision from this session's decide(); one from another session (another call) or made by hand is refused"
      );
    }
    if (!decision.needsModel) {
      throw new Error(
        `record() is for a turn that needed the model; this one was answered by ${
          decision.servedFromFiller ? "a filler" : "the cache"
        } ("${decision.action}")`
      );
    }
    return this._recordDecision(decision, answer, keep, system);
  }

  // record() and answer(): store the answer and fill in the decision.
  async _recordDecision(decision, answer, keep, system = null) {
    decision._recorded = true;
    const said = decision._said;
    decision._said = null;
    decision.text = answer;
    const { outcome, why: reason, rule } = await this._record(said, answer, {
      turn: decision.turn,
      private: keep,
      instructions: system,
    });
    decision.stored = STORED.has(outcome);
    decision.saveRule = decision.stored ? null : rule || null;
    const why = decision.stored ? "" : reason || outcome;
    decision.notStored = why;
    if (!(typeof decision.text === "string" && decision.text.trim())) {
      decision._empty = true;
      decision.reason = "the model returned an empty answer; retry or speak a fallback";
    } else if (why) {
      decision.reason = `${decision.reason}; not stored: ${why}`;
    }
    return decision;
  }

  // answer(), streamed: decide now, then give the text to speak piece by piece.
  //
  // llm(messages) gives the model's text as it writes it: an async iterable or iterable
  // of strings (null pieces are skipped), or the whole answer as a string (or a promise
  // of one). It is called with the same messages answer() would use, only when the turn
  // needs the model, and only once the response is read.
  //
  // A turn the cache or a filler answers yields that text once (decision.audio has its
  // audio when the session caches audio). A model turn yields the model's pieces and,
  // when its stream ends, records the full answer under answer()'s rules (`private` as
  // in record()). If the caller talks over it (cancel()) or a newer turn is decided, the
  // stream stops at the next piece, the model's stream is closed and nothing is stored.
  // A model error rejects and stores nothing, as does stopping early (close(), or
  // leaving the loop); the decision can then still be recorded with record().
  async respond(callerSaid, llm, { system = null, private: keep = false } = {}) {
    const decision = await this.decide(callerSaid);
    return new VoiceResponse(this, decision, callerSaid, llm, system, keep);
  }

  // Which agent's system prompts this call's is compared with.
  _agentKey() {
    const agent = this.agent || {};
    return [agent.tenant || (agent.client && agent.client.tenant) || null, agent.agentId || null];
  }

  // The caller talked over this turn, or a newer turn has been decided.
  _movedOn(decision) {
    return this._cancelled || decision.turn !== this._turn;
  }

  // A streamed turn the caller talked over: report it, store and keep nothing. Not an
  // empty answer, so an app never retries over the caller's new words.
  _interrupted(decision, spoken) {
    if (decision._recorded) return;
    decision._recorded = true;
    decision._said = null;
    decision.text = spoken;
    decision.stored = false;
    decision.saveRule = "Interrupted";
    this._ruleCounts.set("Interrupted", (this._ruleCounts.get("Interrupted") || 0) + 1);
    decision.notStored = "the caller moved on before this answer was complete";
    decision.reason = `${decision.reason}; not stored: ${decision.notStored}`;
  }

  // Keep a turn in this call's transcript and never cache it. For a model that
  // holds the whole conversation itself (a realtime speech model): it cannot be
  // given decision.messages, so nothing it says is shared.
  recordPrivateTurn(callerSaid, modelSaid) {
    this._heard(callerSaid);
    if (this._cancelled) return;
    this._open = false;
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    if (this._shareable[1]) this.notShareable += 1;
    this._shareable = [0, false];
  }

  // Note, in the background, that `answer` was saved for `question`. A failure only means a
  // later hit can't be checked, which is how it was before.
  _keepQuestion(question, answer) {
    const client = this.agent && this.agent.client;
    if (!client || typeof client.set !== "function") return;
    const key = questionKey(tenantOf(this.agent), answer);
    const ttl = this.ttl || QUESTION_TTL;
    const record = (async () => {
      try {
        const raw = await client.get(key);
        let kept = raw ? JSON.parse(String(raw)) : [];
        kept = (Array.isArray(kept) ? kept : []).filter((q) => typeof q === "string" && q !== question).slice(-(QUESTIONS_KEPT - 1));
        await client.set(key, JSON.stringify([...kept, question]), { ttl });
      } catch {
        // see above
      }
    })(); // never on the audio-clip queue
    pendingRecords.add(record);
    record.finally(() => pendingRecords.delete(record));
  }

  // Whether every question this answer was saved for asks about something else. Unknown
  // (no record, or it can't be read in time) means no: as before.
  async _answersAnotherQuestion(asked, answer, spentMs = 0) {
    const client = this.agent && this.agent.client;
    if (!client || typeof client.get !== "function") return false;
    try {
      const read = Promise.resolve().then(() => client.get(questionKey(tenantOf(this.agent), answer)));
      read.catch(() => {});
      const budgeted = this.latencyBudgetMs !== undefined && this.latencyBudgetMs !== null;
      const left = budgeted ? this.latencyBudgetMs - spentMs : null; // what the lookup left of the budget
      if (budgeted && left <= 0) return false;
      const raw = budgeted ? await within(left, read) : await read;
      if (raw === LATE || !raw) return false;
      const questions = JSON.parse(String(raw));
      if (!Array.isArray(questions)) return false;
      const kept = questions.filter((q) => typeof q === "string");
      return kept.length > 0 && kept.every((q) => differentSpecifics(asked, q));
    } catch {
      return false;
    }
  }

  // agent.learn(), waited for no longer than twice the latency budget: a slow server never
  // stalls the turn after a miss. A write still running then finishes in the background
  // (an error it ends with is counted). An error within the budget is thrown, as before.
  // Without a budget it is waited for, as it always was. False when the turn stopped waiting.
  //
  // Resolves to null when the write is done; otherwise to the "slow_write" outcome to
  // report (still running, or not written at all because too many writes wait).
  async _learn(...args) {
    if (this.latencyBudgetMs === undefined || this.latencyBudgetMs === null) {
      await this.agent.learn(...args);
      return null;
    }
    const verdict = await this._writer.write(() => this.agent.learn(...args), 2 * this.latencyBudgetMs);
    return verdict ? { outcome: verdict.outcome, why: verdict.reason, rule: verdict.rule } : null;
  }

  // The ID-like values this caller said earlier in the call: its earlier turns in the
  // transcript and the turns the session only heard (private turns, loaded history).
  // Called once the turn being recorded is in the transcript, so that turn is left out:
  // it passed the personal rules, so its numbers are not private. As in Python.
  _saidIdentifiers() {
    const said = this.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content).slice(0, -1);
    return identifiers([...said, ...[...this._heardTexts].sort()]);
  }

  // A caller turn this session never decided (a private turn, history the app gave the
  // model): one that tells the call something a later answer may depend on keeps the
  // rest of the call off the shared cache, as decide() does for its own turns.
  _heard(callerSaid) {
    const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
    if (this._tainted || !text || this._heardTexts.has(text)) return;
    if (this._heardTexts.size < HEARD_MAX) this._heardTexts.add(text);
    if (setsContext(text)) this._tainted = true;
  }

  // Record the model's answer to the turn decide() last handled, and cache it if
  // allowed. Only an answer written from decision.messages reaches this, so it is
  // shared exactly when decide() said it may be. `turn` is the decision's turn: an
  // answer to a turn the caller talked over, or to one before the latest, is
  // dropped, so it never lands on later words. Never rejects: a refused write
  // (security pipeline, tenant limit, cache down) must not end a call.
  //
  // Resolves to what happened to the answer: "saved" (shared), "template" (shared
  // as a shape, this caller's values removed), "kept" (the model read the whole
  // call, so it stays in this call), "private" (personal, or repeats this caller's
  // details), "non_answer", "not_saved" (a follow-up with nothing to key it to),
  // "refused" (the write failed), "slow_write" (a session with a latency budget stopped
  // waiting for the write: not confirmed) or "interrupted" (talked over, or the caller
  // moved on before it was complete).
  async _recordModelTurn(callerSaid, modelSaid, { turn, private: keep = false } = {}) {
    return (await this._record(callerSaid, modelSaid, { turn, private: keep })).outcome;
  }

  // The same, with why an answer was not stored, in words, and the rule that decided it.
  async _record(callerSaid, modelSaid, options = {}) {
    const recorded = await this._recordAnswer(callerSaid, modelSaid, options);
    if (recorded.rule) this._ruleCounts.set(recorded.rule, (this._ruleCounts.get(recorded.rule) || 0) + 1);
    return recorded;
  }

  // _record without the per-rule count: the save chains, then the write.
  async _recordAnswer(callerSaid, modelSaid, { turn, private: keep = false, instructions = null } = {}) {
    const outcome = (word, why = "", rule = null) => ({ outcome: word, why, rule });
    if (this._cancelled || (turn !== undefined && turn !== null && turn !== this._turn)) {
      return outcome("interrupted", "the caller moved on before this answer was complete", "Interrupted");
    }
    this._open = false;
    const expected = turn === undefined || turn === null ? this._turn : turn;
    const shareable = this._shareable;
    this._shareable = [0, false];
    let answer = new ModelAnswer(callerSaid, modelSaid, null, this._call, {
      private: keep, instructions, cacheable: shareable[1] && shareable[0] === expected,
    });
    let verdict = this._rules.answerGiven.firstObjection(answer);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._kept(verdict);
    answer = answer.keyed(this._contextKey(callerSaid, answer.text));
    this.transcript.push({ role: "user", content: callerSaid });
    this.transcript.push({ role: "assistant", content: modelSaid });
    verdict = this._rules.beforeSharing.firstObjection(answer);
    if (RuleChain.isPending(verdict)) verdict = await verdict;
    if (verdict) return this._kept(verdict);
    try {
      if (answer.isPersonal) return await this._recordPersonal(answer);
      verdict = this._rules.sharing.firstObjection(answer);
      if (RuleChain.isPending(verdict)) verdict = await verdict;
      if (verdict) return this._kept(verdict);
      const slow = await this._learn(answer.key, modelSaid, { ttl: this.ttl });
      this._lastStored = answer.key;
      if (!slow) this._keepQuestion(answer.key, modelSaid); // a slow server gets no extra write
      return slow || outcome("saved");
    } catch (error) {
      this.learnErrors += 1;
      return outcome(
        "refused",
        `the server refused the write: ${(error && error.message) || (error && error.name) || String(error)}`,
        "WriteRefused"
      );
    }
  }

  // A personal answer is shared only as a shape with this call's values taken out.
  async _recordPersonal(answer) {
    const personal = this._rules.personal;
    let verdict = personal.check(answer);
    if (!verdict) {
      const templated = await this._learnPersonal(answer.key, answer.answer);
      if (templated && templated.outcome) return templated; // slow_write: the shape was not confirmed written
      if (templated) return { outcome: "template", why: "", rule: null };
      verdict = personal.refusal();
    }
    return this._kept(verdict);
  }

  // A save rule kept the answer out of the shared cache.
  _kept(verdict) {
    this._countVerdict(verdict);
    return { outcome: verdict.outcome, why: verdict.reason, rule: verdict.rule };
  }

  injections() {
    return this.transcript.slice();
  }

  /** The counts the Voice page shows, by the server's names. */
  _reportable() {
    return {
      turns: this.served + this.inferred + this.filled,
      served_from_cache: this.served,
      filler_hits: this.filled,
      model_calls_avoided: this.served + this.filled,
      private_turns: this.refusedPrivate + this.uncacheablePersonal,
      barge_ins: this.bargeIns,
      latency_misses: this.overBudget,
      empty_answers: this.emptyAnswers,
    };
  }

  /**
   * Send this session's counts since its last report to the Voice page (the server's Voice add-on).
   * false when the server has no Voice add-on. Nothing is lost: what a failed report did not send
   * goes with the next.
   */
  async reportStats() {
    const now = this._reportable();
    const sent = {};
    for (const [name, count] of Object.entries(now)) {
      const fresh = count - (this._reported[name] || 0);
      if (fresh > 0) sent[name] = Math.min(fresh, REPORT_MAX);
    }
    if (!Object.keys(sent).length) return true;
    try {
      await this.agent.client.cvoicestat(sent, { tenant: this.agent.tenant });
    } catch (error) {
      if (voiceAddonMissing(error)) return false;
      throw error;
    }
    for (const [name, count] of Object.entries(sent)) this._reported[name] = (this._reported[name] || 0) + count;
    return true;
  }

  stats() {
    const total = this.served + this.inferred + this.filled;
    const pct = (count) => (total ? Math.round((10000 * count) / total) / 100 : 0);
    return {
      turns: total,
      servedFromCache: this.served,
      answeredByFiller: this.filled,
      modelCalls: this.inferred,
      refusedTooShort: this.refusedShort,
      refusedToShareAPrivateAnswer: this.refusedPrivate,
      uncacheablePersonal: this.uncacheablePersonal,
      missedLatencyBudget: this.overBudget,
      bargeIns: this.bargeIns,
      cacheUnavailable: this.lookupErrors,
      failedWrites: this.learnErrors,
      slowWrites: this.slowWrites,
      differentQuestion: this.differentQuestion,
      notShareable: this.notShareable,
      commitmentsSentToModel: this.heldCommitments,
      unspeakableAnswers: this.unspeakable,
      emptyAnswers: this.emptyAnswers,
      audioUnavailable: this.audioUnavailable,
      cacheHitPct: pct(this.served),
      fillerHitPct: pct(this.filled),
      modelCallsAvoidedPct: pct(this.served + this.filled),
      // How often each rule decided a turn or kept an answer, by the rule's name.
      rules: Object.fromEntries([...this._ruleCounts].sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))),
    };
  }

  _hasValues() {
    return Object.keys(this.values).length > 0;
  }

  // The earlier caller turns a follow-up leans on, oldest first: back to the
  // latest one that stands on its own. null when there is no such turn.
  _chain() {
    const chain = [];
    for (let index = this.transcript.length - 1; index >= 0; index -= 1) {
      const turn = this.transcript[index];
      if (turn.role !== "user") continue;
      chain.unshift(turn.content);
      if (!isContextDependent(typeof turn.content === "string" ? turn.content.trim() : "")) return chain;
      if (chain.length >= CHAIN_LIMIT) return null;
    }
    return null;
  }

  // A short turn after a private emergency or medical turn ("is he going to be
  // okay?", "how do i make her vomit?"): about that turn, so answered with the call.
  _afterUrgent(text) {
    if (wordsOf(text).length > FOLLOW_UP_WORDS) return false;
    const earlier = this.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    for (const said of earlier.slice(-CHAIN_LIMIT).reverse()) {
      const words = wordsOf(said);
      if ((words.some((w) => URGENT.has(w)) || urgent(words)) && isPersonal(said)) return true;
      if (words.length > FOLLOW_UP_WORDS) return false;
    }
    return false;
  }

  _contextKey(callerSaid, text) {
    if (!isContextDependent(text)) return callerSaid;
    const chain = this._chain();
    if (chain === null) return null;
    return [...chain, callerSaid].join(" || ");
  }

  // Store a personal answer as a shape. False when it cannot be made generic, or when
  // this session does not share templates.
  async _learnPersonal(keyed, modelSaid) {
    if (!this.shareTemplates) {
      this.uncacheablePersonal += 1;
      return false;
    }
    const shaped = abstract(modelSaid, this.values);
    // The model read the whole call: what is left outside the slots must say nothing
    // of this caller that was not declared (a name, an address, a number, a matter).
    const outside = shaped.replace(SLOT, " ");
    const words = wordsOf(outside);
    const earlier = this.transcript.filter((turn) => turn.role === "user").map((turn) => turn.content || "");
    const undeclared =
      words.some((w) => hasDigit(w) || AMOUNT_WORDS.has(w) || MATTERS.has(w)) ||
      readsOutDigits(outside, words) || EMAIL.test(outside) || identifies(outside, words) ||
      carriesCallContext(outside, keyed, earlier);
    if (this._hasValues() && slotNames(shaped).length && !leaks(shaped, this.values) && !undeclared) {
      return (await this._learn(keyed, shaped, { ttl: this.ttl, template: true })) || true;
    }
    this.uncacheablePersonal += 1;
    return false;
  }

  // The audio for an answer this turn speaks, or null. Never rejects: when the audio
  // step fails (the cache, or the app's own synthesiser) the turn keeps its text and the
  // app's TTS speaks it. It used to reject the whole turn, losing the cached answer.
  async _voiced(answer, { cacheable = true } = {}) {
    if (!this.synthesise) return null;
    try {
      return await this._voice(answer, cacheable);
    } catch (error) {
      this.audioUnavailable += 1;
      // The type only: an app's TTS error can quote the (possibly personal) text.
      console.warn(`crowkis voice: no audio for this answer, the text is still served (${(error && error.name) || typeof error})`);
      return null;
    }
  }

  async _voice(answer, cacheable) {
    // A text-only session (voiceSession() with no voice) has no real voice id to key a
    // clip on: speak, but never read or store a cached clip.
    if (!cacheable || this._textOnly) return this.synthesise(answer);
    return this.agent.speak(answer, this.synthesise, {
      voice: this.voice,
      ttl: this.ttl,
      language: this.language,
      speed: this.speed,
      audioFormat: this.audioFormat,
      bytesPerSecond: this.bytesPerSecond,
    });
  }
}

/**
 * Fill the cache from past calls, so it is useful on the first day.
 *
 * `calls` is an iterable of calls, each an array of `[callerSaid, agentSaid]`
 * turns in order. A follow-up is kept with the turn it depends on, and nothing
 * is spoken or synthesised.
 *
 * It needs the server's decision engine, holding answers until it has judged
 * them (the default), and throws otherwise. A past agent turn can hold
 * details the caller never said aloud (an address looked up, a balance),
 * which the live rules cannot see in a transcript; the engine reads every
 * answer before anyone is served it.
 *
 * Resolves to totals. After each call it gives the engine up to `wait`
 * seconds to catch up; `stalled` is true when it stopped early because three
 * calls in a row were not judged in that time.
 */
async function warmFromCalls(agent, calls, { wait = 30 } = {}) {
  if (!((await agent.decides()) && agent._holds)) {
    throw new Error(
      "warmFromCalls needs the server's decision engine, holding answers until it has judged " +
        "them (CROWKIS_DECIDE_UPSTREAM set, CROWKIS_DECIDE_SERVE_UNJUDGED not set): otherwise a " +
        "past answer holding one caller's details could be shared before it is checked"
    );
  }
  const totals = { calls: 0, turns: 0, keptPrivate: 0, failedWrites: 0, stalled: false };
  let stalls = 0;
  for (const call of calls) {
    const session = new VoiceSession(agent, { voice: "warm-start" });
    const earlier = [];
    for (const [callerSaid, agentSaid] of call) {
      // The same rule as a live turn picks the candidates. A past answer was
      // written with the whole call in view, so one that repeats what
      // identified this caller is kept out here, and the engine reads the rest
      // before anyone is served them.
      const text = typeof callerSaid === "string" ? callerSaid.trim() : "";
      const keyed = session._contextKey(callerSaid, text) || callerSaid;
      session._tainted = session._tainted || setsContext(text);
      session._shareable = [
        session._turn,
        session._modelMessages(callerSaid)[1] && !carriesCallContext(agentSaid, keyed, earlier),
      ];
      await session._recordModelTurn(callerSaid, agentSaid);
      earlier.push(callerSaid);
      totals.turns += 1;
    }
    totals.calls += 1;
    totals.keptPrivate += session.notShareable + session.uncacheablePersonal;
    totals.failedWrites += session.learnErrors;
    // Let the engine catch up before the next call: it judges a bounded
    // number of answers at a time and refuses what does not fit.
    stalls = (await judgedInTime(agent, session._lastStored, wait * 1000)) ? 0 : stalls + 1;
    if (stalls >= 3) {
      totals.stalled = true;
      break;
    }
  }
  return totals;
}

/** False when the engine was still working on `query` after `ms`. */
async function judgedInTime(agent, query, ms) {
  const deadline = Date.now() + ms;
  while (query && Date.now() < deadline) {
    let view;
    try {
      view = await agent.explain(query);
    } catch (_error) {
      // Cannot ask, so there is nothing to wait for.
      return true;
    }
    if (!(view && view.pending)) return true;
    await new Promise((resolve) => setTimeout(resolve, Math.min(200, ms)));
  }
  return !query;
}

// The voice id of a text-only session. Never used as a cache key: every audio path
// checks `_textOnly` first.
const TEXT_ONLY_VOICE = "crowkis:text-only";

// Every option new VoiceSession() takes, so a misspelt one is an error here, as in Python.
const SESSION_OPTIONS = new Set([
  "serveAbove", "minWords", "synthesise", "ttl", "fillers", "values", "commitments",
  "shortTurns", "shareTemplates", "language", "speed", "audioFormat", "bytesPerSecond",
]);

/**
 * A ready VoiceSession in one call, with defaults for live calls (same as Python's
 * crowkis.voice_session()).
 *
 * It builds the client and the Agent itself. Server settings not passed here come from
 * the environment, then the defaults (see the README, "Connect to your server"). The
 * defaults differ from a bare VoiceSession because a caller is waiting:
 * - latencyBudgetMs 250: the longest a turn waits for a cache lookup before it goes to
 *   the model. null turns the budget off.
 * - timeoutMs 1000 per server request, with no retries. Saving the model's answer
 *   happens while the caller waits; 5 s tried three times would leave a stuck server
 *   holding the turn for about 15 s. The cost of no retries: a request that fails once
 *   (the first after a server restart, or a BUSY reply) is not tried again, so that
 *   lookup goes to the model or that answer is not stored. Pass your own `client` for
 *   other settings, e.g. for warmFromCalls, which should not use this live-call client.
 *
 * `voice` is the TTS voice id. Without it the session caches text only and never reads
 * or stores audio, so two voices can never share a clip; passing `synthesise` then is
 * an error. Every other VoiceSession option is passed on as it is.
 *
 * `client` uses a client you built, as it is: passing host/port/authToken/token/tenant/
 * timeoutMs with it is an error, and closing the agent leaves it open.
 */
function voiceSession(options = {}) {
  const {
    voice,
    agentId = "voice",
    client: given,
    host,
    port,
    authToken,
    auth_token: authTokenAlias,
    token,
    tenant,
    timeoutMs,
    latencyBudgetMs = 250,
    ...rest
  } = options;
  if (timeoutMs !== undefined && timeoutMs !== null && !(timeoutMs > 0)) {
    throw new Error(`timeoutMs must be a positive number of milliseconds, got ${timeoutMs}`);
  }
  const unknown = Object.keys(rest).filter((name) => !SESSION_OPTIONS.has(name));
  if (unknown.length) {
    throw new TypeError(`voiceSession() got unknown option(s): ${unknown.join(", ")}`);
  }
  if (given) {
    const passed = Object.entries({ host, port, authToken, auth_token: authTokenAlias, token, tenant, timeoutMs })
      .filter(([, value]) => value !== undefined && value !== null)
      .map(([name]) => name);
    if (passed.length) {
      throw new Error(
        `voiceSession() got client and ${passed.join(", ")}: a client passed in is used as it is, ` +
          "so set these on the client instead"
      );
    }
  }
  const textOnly = voice === undefined || voice === null;
  if (textOnly && rest.synthesise) {
    throw new Error(
      "voiceSession() got synthesise without voice. Cached audio is keyed on the voice that " +
        "spoke it: pass your TTS voice id, or leave out synthesise to cache text only"
    );
  }
  const client =
    given ||
    new CrowkisClient({
      host,
      port,
      authToken: authToken || authTokenAlias || token,
      tenant,
      timeoutMs: timeoutMs ?? 1000,
      maxRetries: 0,
    });
  const agent = new Agent(agentId, { client, tenant: client.tenant });
  agent._ownsClient = !given;
  const session = new VoiceSession(agent, {
    ...rest,
    voice: textOnly ? TEXT_ONLY_VOICE : voice,
    latencyBudgetMs,
  });
  session._textOnly = textOnly;
  return session;
}

module.exports = {
  VoiceSession,
  VoiceResponse,
  TurnDecision,
  voiceSession,
  warmFromCalls,
  _SESSION_OPTIONS: SESSION_OPTIONS,
  _speakable: speakable,
  _words: wordsOf,
  _promptDetails: promptDetails,
  _repeatsPromptDetails: repeatsPromptDetails,
  _callerDetails: callerDetails,
  _resetPromptBaselines: resetPromptBaselines,
  _differentSpecifics: differentSpecifics,
  _waitForWrites: waitForWrites,
  _setWritesMax: setWritesMax,
  _isPersonal: isPersonal,
  _IPV4: IPV4,
  _PII_PLACEHOLDER: PII_PLACEHOLDER,
  _isContextDependent: isContextDependent,
  _setsContext: setsContext,
  _tellsFacts: tellsFacts,
  _tellsAboutCaller: tellsAboutCaller,
  _instructs: instructs,
  _urgent: urgent,
  _wordsOf: wordsOf,
  _identifying: identifying,
  _properNouns: properNouns,
  _isNonAnswer: isNonAnswer,
  _abstract: abstract,
  _fill: fill,
};
