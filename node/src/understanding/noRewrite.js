"use strict";

/**
 * Null Object for the rewriter slot: no stand-alone question, so a turn's cache key stays the
 * caller's own words (or the chain a follow-up leans on), as today.
 */
class NoRewrite {
  rewrite() {
    return null;
  }
}

module.exports = { NoRewrite };
