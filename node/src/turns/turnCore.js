"use strict";

const { Checked, LookedUp } = require("./checked.js");

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
 * the write (the one place a failed write becomes an outcome), then the channel notes what was
 * recorded.
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
    let outcome;
    try {
      outcome = await this._saving.write(checked.subject);
    } catch (error) {
      outcome = this._report.refused(error);
    }
    return this._report.recorded(answered, outcome);
  }
}

module.exports = { CHEAP_ABOVE, TurnCore, isThenable };
