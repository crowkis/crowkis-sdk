"use strict";

const { OUTCOME } = require("../turns/outcome.js");
const { Verdict } = require("../turns/verdict.js");
const { COUNTER } = require("./stats.js");
const { WRITTEN, WriteResult } = require("./writeResult.js");

const BOUNDED_WRITE = "BoundedWrite";
const NOT_STORED = "NotStored";
const NOT_STORED_REASON = "not stored: the server accepted the answer and kept nothing (NOTSTORED)";
const NOT_WRITTEN_REASON = "not written: too many writes are waiting on a slow server";
const NOT_CONFIRMED_REASON =
  "not confirmed: the server took longer than the latency budget, so the write finishes in the background";
// A turn waits for its answer's write at most this many latency budgets.
const BUDGETS_PER_WRITE = 2;

/**
 * A cache write a live turn waits for no longer than its deadline: a slow server never stalls the
 * turn after a miss. A write still running then finishes in the background (an error it ends with
 * is counted). Past maxPending() writes already waiting on a slow server, a new answer is not
 * written. `pending` is the process-wide set of writes in the background; `maxPending` is read
 * when a write starts; `count` adds to a session counter; `warn` logs. All injected.
 */
class BoundedWriter {
  constructor(pending, maxPending, count, warn) {
    this._pending = pending;
    this._maxPending = maxPending;
    this._count = count;
    this._warn = warn;
  }

  /**
   * write() waited for no longer than twice the turn's latency budget; without a budget (null or
   * undefined) the store is waited for, as it always was. Voice and chat both write this way.
   * Resolves to a WriteResult.
   *
   * The write's one error boundary: a store that fails before the deadline (a security pipeline
   * refusal, a tenant limit, the cache down) is a refused result, never a rejection that ends the
   * call; the channel reports it.
   */
  async writeWithin(store, budgetMs) {
    try {
      if (budgetMs === null || budgetMs === undefined) {
        if ((await store()) === false) return new WriteResult(new Verdict(NOT_STORED, NOT_STORED_REASON, [], OUTCOME.NOT_SAVED));
        return WRITTEN;
      }
      // Awaited here, so the write takes one step, as it did when each session waited for it itself.
      return new WriteResult(await this.write(store, BUDGETS_PER_WRITE * budgetMs));
    } catch (error) {
      return new WriteResult(null, error);
    }
  }

  /**
   * Resolves to null when the write is done; otherwise to the BoundedWrite verdict (not written,
   * or not confirmed in time). An error before the deadline is thrown, as before.
   */
  async write(store, deadlineMs) {
    if (this._pending.size >= this._maxPending()) {
      this._count(COUNTER.SLOW_WRITES);
      this._warn("crowkis voice: too many writes waiting on a slow server; this answer is not written");
      return new Verdict(BOUNDED_WRITE, NOT_WRITTEN_REASON, [], OUTCOME.SLOW_WRITE);
    }
    let kept = true;
    let late = false; // set by the timer itself, so an error at any later moment is counted here
    const write = Promise.resolve().then(store);
    const tracked = write
      .catch((error) => {
        if (!late) return; // before the turn stopped waiting: thrown to the caller, counted there
        this._count(COUNTER.LEARN_ERRORS);
        this._warn(`crowkis voice: a write that passed the latency budget then failed (${(error && error.name) || "Error"})`);
      })
      .finally(() => this._pending.delete(tracked));
    this._pending.add(tracked);
    const finished = await new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        late = true;
        resolve(false);
      }, deadlineMs);
      write.then(
        (value) => { clearTimeout(timer); kept = value !== false; resolve(true); },
        (error) => { clearTimeout(timer); if (!late) reject(error); }
      );
    });
    if (finished) return kept ? null : new Verdict(NOT_STORED, NOT_STORED_REASON, [], OUTCOME.NOT_SAVED);
    this._count(COUNTER.SLOW_WRITES);
    return new Verdict(BOUNDED_WRITE, NOT_CONFIRMED_REASON, [], OUTCOME.SLOW_WRITE);
  }
}

module.exports = { BoundedWriter };
