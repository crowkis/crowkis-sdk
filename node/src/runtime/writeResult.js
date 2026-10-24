"use strict";

/**
 * What a bounded write did: `written` when the store finished in time; otherwise `objection` is the
 * BoundedWrite verdict saying why not (slow_write: not written because too many writes wait on a slow
 * server, or not confirmed within the deadline). Immutable.
 */
class WriteResult {
  constructor(objection = null) {
    this.objection = objection;
    Object.freeze(this);
  }

  /** Whether the store finished in time. */
  get written() {
    return this.objection === null;
  }
}

const WRITTEN = new WriteResult();

module.exports = { WRITTEN, WriteResult };
