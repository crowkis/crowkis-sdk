"use strict";

// Stage 1 rules (question): about this caller (own records).

const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");

const OWN_RECORDS_REASON =
  "the caller asked about their own records and this session has no values " +
  "to fill a shared answer shape with, so nothing can be answered from " +
  "cache without one caller's answer reaching the next";

/**
 * A question about the caller's own records ("where is my order 48213"), or another turn the
 * word rules never share (urgent, identifying, unreadable), is never answered from the shared
 * cache unless this call declared values to fill a shared answer shape with.
 */
class OwnRecords {
  get name() {
    return "OwnRecords";
  }

  get floor() {
    return true;
  }

  check(turn) {
    if (!turn.isPersonal || turn.call.hasValues) return null;
    return new Verdict(this.name, OWN_RECORDS_REASON, [COUNTER.REFUSED_PRIVATE, COUNTER.INFERRED]);
  }
}

module.exports = { OwnRecords };
