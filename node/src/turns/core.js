"use strict";

// TurnCore: one turn of any channel, from what the caller said to a result, and from the model's
// answer to what is shared; and the step interfaces it calls.

const { Checked, LookedUp } = require("./values.js");

// The parts TurnCore's fixed steps call: one small interface per step, each with a voice and a chat
// implementation that the facades (the composition roots) pick. JSDoc only: Node has no Protocol.
// A step marked "or a promise" answers at once unless it has to wait (a plugged-in model, a server
// read); TurnCore awaits only a promise, so a turn that waits for nothing keeps its timing.

/**
 * The call's settings a lookup reads, live: an app may change them between turns.
 * @typedef {object} CallSettings
 * @property {object} agent the agent lookups go through
 * @property {number} serveAbove the confidence a cached answer needs to be served
 * @property {number|null|undefined} latencyBudgetMs the lookup's budget (null: wait as long as the cache takes)
 */

/**
 * Which turn an answer belongs to (TurnPairing, ChatTurns).
 * @typedef {object} Pairing
 * @property {() => number} open a turn is being decided: its number
 * @property {(answered: object) => import("./checked.js").Checked} settle the answer paired with its
 *   turn, or the objection that drops it (the caller moved on)
 */

/**
 * Answers a turn gets without the cache or the model (VoiceReport, ChatAnswers).
 * @typedef {object} EarlyAnswers
 * @property {(said: string, turn: number) => object|null} beforeReading the channel's result for turn
 *   number `turn`, answered before it is read, or null
 * @property {(checked: import("./checked.js").Checked) => object|null|Promise<object|null>} afterCheck the
 *   channel's result for a turn the question check stopped and something other than the model answers
 *   (a filler, an app's hook), or null
 */

/**
 * How a turn is understood (VoiceReader, ChatReader).
 * @typedef {object} TurnReader
 * @property {(said: string, turn: number) => object|Promise<object>} read turn number `turn`, read: what
 *   the question and hit checks see
 */

/**
 * Stage 1: whether a turn may be looked up and shared (RuleSet, ChatQuestionCheck).
 * @typedef {object} QuestionCheck
 * @property {(turn: object) => import("./checked.js").Checked|Promise<import("./checked.js").Checked>} checkQuestion
 *   the turn as checked (keyed, for a chat) and the first objection, if any
 */

/**
 * Stage 2: whether a hit may be served (RuleSet, ChatHitCheck).
 * @typedef {object} HitCheck
 * @property {(turn: object, hit: object, started: number) => import("./checked.js").Checked} checkHit
 *   the hit as the hit rules read it and the objection to serving it, if any (it may still be pending)
 */

/**
 * Adapter: the channel's public results, counts and events for what the core found (VoiceReport, ChatReport).
 * @typedef {object} Report
 * @property {(checked: import("./checked.js").Checked) => object} toModel the question check stopped the
 *   turn: the model answers with the whole call
 * @property {(checked: import("./checked.js").Checked, looked: import("./checked.js").LookedUp) => object} missed
 *   no hit may be served: the model answers the turn
 * @property {(checked: import("./checked.js").Checked, looked: import("./checked.js").LookedUp) => object|Promise<object>} served
 *   a hit is served (`looked.cached`)
 * @property {(verdict: import("./verdict.js").Verdict) => any} kept an answer is not saved (dropped or
 *   kept out of the shared cache): the outcome
 * @property {(answered: object, outcome: any) => any} recorded whatever happened to an answer: counted or
 *   reported as the channel does; the outcome
 */

/**
 * Stage 3 and the write (VoiceSaving, ChatSaving).
 * @typedef {object} Saving
 * @property {(answered: object) => import("./checked.js").Checked|Promise<import("./checked.js").Checked>} check
 *   the answer as the save rules read it, and the objection to saving it, if any
 * @property {(answer: object) => Promise<any>} write share the answer and write it, within the bounded
 *   write: the outcome
 */

// The confidence above which the agent may route a hit to a cheaper model (capped by serveAbove).
const CHEAP_ABOVE = 0.6;

/** A plugged-in model's slot, a rule that asked the server or an app's hook may answer with a promise. */
function isThenable(value) {
  return value !== null && typeof value === "object" && typeof value.then === "function";
}

/**
 * Template Method: the fixed steps of a turn of any channel. decide(): open (number) the turn,
 * answers before reading, read it, the question check, an early answer, the lookup inside the budget,
 * the hit check, serve or hand to the model. record(): pair the answer with its turn, the save check,
 * the write (a failed write comes back from the writer's boundary as an outcome), then the channel
 * notes what was recorded.
 *
 * What differs between channels is injected (see turnSteps.js); the facades pick the parts.
 * `settings` is the call's live settings (agent, serveAbove, latencyBudgetMs). A step that answers
 * at once is never awaited, so a turn that waits for nothing keeps its timing.
 */
class TurnCore {
  /**
   * @param {import("./turnSteps.js").CallSettings} settings
   * @param {{ pairing: import("./turnSteps.js").Pairing, answers: import("./turnSteps.js").EarlyAnswers,
   *   reader: import("./turnSteps.js").TurnReader, questionCheck: import("./turnSteps.js").QuestionCheck,
   *   cacheLookup: import("../runtime/cacheLookup.js").CacheLookup, hitCheck: import("./turnSteps.js").HitCheck,
   *   report: import("./turnSteps.js").Report, saving: import("./turnSteps.js").Saving }} parts
   */
  constructor(settings, { pairing, answers, reader, questionCheck, cacheLookup, hitCheck, report, saving }) {
    this._settings = settings;
    this._pairing = pairing;
    this._answers = answers;
    this._reader = reader;
    this._questionCheck = questionCheck;
    this._cacheLookup = cacheLookup;
    this._hitCheck = hitCheck;
    this._report = report;
    this._saving = saving;
  }

  /** The channel's result for this turn: an early answer, a cached answer, or the model's turn. */
  async decide(said) {
    const turn = this._pairing.open();
    const early = this._answers.beforeReading(said, turn);
    if (early !== null && early !== undefined) return early;
    let reading = this._reader.read(said, turn);
    if (isThenable(reading)) reading = await reading;
    let checked = this._questionCheck.checkQuestion(reading);
    if (isThenable(checked)) checked = await checked;
    if (isThenable(checked.objection)) checked = new Checked(checked.subject, await checked.objection);
    if (checked.objection) {
      let answered = this._answers.afterCheck(checked);
      if (isThenable(answered)) answered = await answered;
      return answered ?? this._report.toModel(checked);
    }
    // lookUp()'s steps, inline: the lookup's own promise is awaited here, with no extra step between.
    const started = performance.now();
    let looked = this._checkHit(checked.subject, await this._find(checked.subject, started), started);
    if (isThenable(looked.objection)) looked = new LookedUp(looked.hit, looked.cached, await looked.objection);
    if (looked.objection) return this._report.missed(checked, looked);
    const served = this._report.served(checked, looked);
    return isThenable(served) ? await served : served;
  }

  /** The cache's hit for a turn's key, within the budget, and the hit check's word on it (a LookedUp). */
  async lookUp(turn) {
    const started = performance.now();
    let looked = this._checkHit(turn, await this._find(turn, started), started);
    if (isThenable(looked.objection)) looked = new LookedUp(looked.hit, looked.cached, await looked.objection);
    return looked;
  }

  // The lookup inside the budget the call has now. Not async: its promise is awaited by the caller.
  _find(turn, started) {
    const settings = this._settings;
    const ask = () => settings.agent.ask(turn.key, {
      serveAbove: settings.serveAbove,
      cheapAbove: Math.min(CHEAP_ABOVE, settings.serveAbove),
      ...turn.lookupOptions,
    });
    return this._cacheLookup.find(ask, started, settings.latencyBudgetMs);
  }

  // What the lookup found ({ hit, verdict }), with the hit check's word on a hit it may serve (that
  // word may still be pending: the caller awaits it).
  _checkHit(turn, { hit, verdict }, started) {
    if (verdict) return new LookedUp(hit, null, verdict);
    const found = this._hitCheck.checkHit(turn, hit, started);
    return new LookedUp(hit, found.subject, found.objection);
  }

  /**
   * What happens to the model's answer: dropped when the caller moved on, kept out of the shared cache
   * by a save rule, or shared. Never rejects for the write: a refused write (security pipeline, tenant
   * limit, cache down) must not end a call; the channel reports it. The pairing, the save check and
   * the write are one async step, so an answer's outcome takes no extra step.
   */
  async record(answered) {
    const paired = this._pairing.settle(answered);
    if (paired.objection) return this._report.recorded(answered, this._report.kept(paired.objection));
    let checked = this._saving.check(paired.subject);
    if (isThenable(checked)) checked = await checked;
    let objection = checked.objection;
    if (isThenable(objection)) objection = await objection;
    if (objection) return this._report.recorded(answered, this._report.kept(objection));
    return this._report.recorded(answered, await this._saving.write(checked.subject));
  }
}

module.exports = { CHEAP_ABOVE, TurnCore, isThenable };
