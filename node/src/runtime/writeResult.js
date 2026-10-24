"use strict";

/**
 * What a bounded write did: `written` when the store finished in time. Otherwise either `objection` is
 * the BoundedWrite verdict saying why not (slow_write: not written because too many writes wait on a
 * slow server, or not confirmed within the deadline), or the store failed before the deadline
 * (`refused`: the server refused the write, or the cache is down) with `error`. Immutable.
 */
class WriteResult {
  constructor(objection = null, error = null) {
    this.objection = objection;
    this.error = error;
    Object.freeze(this);
  }

  /** Whether the store finished in time. */
  get written() {
    return this.objection === null && this.error === null;
  }

  /** Whether the store failed before the deadline. */
  get refused() {
    return this.error !== null;
  }
}

const WRITTEN = new WriteResult();

module.exports = { WRITTEN, WriteResult };
