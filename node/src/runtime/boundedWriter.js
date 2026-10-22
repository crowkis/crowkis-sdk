"use strict";

const { Verdict } = require("../turns/verdict.js");

const SLOW_WRITE = "slow_write";
const NOT_WRITTEN_REASON = "not written: too many writes are waiting on a slow server";
const NOT_CONFIRMED_REASON =
  "not confirmed: the server took longer than the latency budget, so the write finishes in the background";

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
   * Resolves to null when the write is done; otherwise to the BoundedWrite verdict (not written,
   * or not confirmed in time). An error before the deadline is thrown, as before.
   */
  async write(store, deadlineMs) {
    if (this._pending.size >= this._maxPending()) {
      this._count("slowWrites");
      this._warn("crowkis voice: too many writes waiting on a slow server; this answer is not written");
      return new Verdict("BoundedWrite", NOT_WRITTEN_REASON, [], SLOW_WRITE);
    }
    let late = false; // set by the timer itself, so an error at any later moment is counted here
    const write = Promise.resolve().then(store);
    const tracked = write
      .catch((error) => {
        if (!late) return; // before the turn stopped waiting: thrown to the caller, counted there
        this._count("learnErrors");
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
        () => { clearTimeout(timer); resolve(true); },
        (error) => { clearTimeout(timer); if (!late) reject(error); }
      );
    });
    if (finished) return null;
    this._count("slowWrites");
    return new Verdict("BoundedWrite", NOT_CONFIRMED_REASON, [], SLOW_WRITE);
  }
}

module.exports = { BoundedWriter };
