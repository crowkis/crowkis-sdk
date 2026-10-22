"use strict";

// The RegisteredFiller rule (stage 1, question; operational).

const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");
const { normalise } = require("../../understanding/wordRules/index.js");

const FILLER_ROUTE = "filler";
const FILLER_REASON = "registered filler, answered without a lookup or a model";

/**
 * A turn the app registered a filler for ("hello") is answered with it at once: no lookup and no
 * model. `fillers` is the session's own Map (normalised trigger to reply), read live.
 */
class RegisteredFiller {
  constructor({ fillers = new Map() } = {}) {
    this._fillers = fillers instanceof Map ? fillers : new Map(Object.entries(fillers));
  }

  get name() {
    return "RegisteredFiller";
  }

  get floor() {
    return false;
  }

  check(turn) {
    const filler = this._fillers.get(normalise(turn.text));
    if (filler === undefined) return null;
    return new Verdict(this.name, FILLER_REASON, [COUNTER.FILLED], null, FILLER_ROUTE, filler);
  }
}

module.exports = { RegisteredFiller };
