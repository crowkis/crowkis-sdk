"use strict";

const { Verdict } = require("../turns/verdict.js");
const { LATE, within } = require("./deadline.js");
const { COUNTER } = require("./stats.js");

// The counters a lookup that failed open adds to: a voice session's by default.
const DEADLINE_COUNTS = Object.freeze([COUNTER.OVER_BUDGET, COUNTER.INFERRED]);
const UNAVAILABLE_COUNTS = Object.freeze([COUNTER.LOOKUP_ERRORS, COUNTER.INFERRED]);

/**
 * The one place a lookup fails open: a hard deadline (a slow or hung cache never holds a live call
 * past its budget, and a hit that comes back late is refused), and an unreachable cache means the
 * model answers. Resolves to { hit, verdict }: the verdict (LookupDeadline or CacheUnavailable)
 * when the model must answer instead. `budgetMs` is the call's budget at the time of the lookup;
 * null or undefined waits as long as the cache takes. `deadlineCounts` / `unavailableCounts` are the
 * counters each verdict adds to (the channel's names).
 */
class CacheLookup {
  // Voice refuses a hit that came back after the budget; Chat never did, and keeps that.
  constructor({ refuseLateHits = true, deadlineCounts = DEADLINE_COUNTS, unavailableCounts = UNAVAILABLE_COUNTS } = {}) {
    this._refuseLateHits = refuseLateHits;
    this._deadlineCounts = deadlineCounts;
    this._unavailableCounts = unavailableCounts;
  }

  async find(ask, started, budgetMs) {
    try {
      const lookup = ask();
      const budgeted = budgetMs !== undefined && budgetMs !== null;
      const hit = budgeted ? await within(budgetMs, lookup) : await lookup;
      // Cut off a slow lookup, and refuse one that finished after the budget.
      if (hit === LATE || (this._refuseLateHits && budgeted && performance.now() - started > budgetMs)) {
        lookup.catch(() => {});
        const reason = `lookup passed the ${budgetMs}ms voice budget; a late hit is worse than a fast miss`;
        return { hit: null, verdict: new Verdict("LookupDeadline", reason, this._deadlineCounts) };
      }
      return { hit, verdict: null };
    } catch (error) {
      // An unreachable or refusing cache means "ask the model", never silence.
      const reason = `cache unavailable (${error && error.name}); asking the model`;
      return { hit: null, verdict: new Verdict("CacheUnavailable", reason, this._unavailableCounts) };
    }
  }
}

module.exports = { CacheLookup };
