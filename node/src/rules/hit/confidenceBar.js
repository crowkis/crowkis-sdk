"use strict";

// The ConfidenceBar rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

const CACHE_ROUTE = "cache";

/** A hit below the spoken-answer bar (or a miss) goes to the model. */
class ConfidenceBar {
  get name() {
    return "ConfidenceBar";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (cached.hit.route === CACHE_ROUTE) return null;
    return new Verdict(this.name, `confidence below the spoken-answer bar of ${cached.turn.call.serveAbove}`, [COUNTER.INFERRED]);
  }
}

module.exports = { ConfidenceBar };
