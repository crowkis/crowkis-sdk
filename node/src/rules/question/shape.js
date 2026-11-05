"use strict";

// Stage 1 rules (question): the turn's shape (empty, short, cut off, a filler).

const { Verdict } = require("../../turns/values.js");
const { COUNTER } = require("../../runtime/stats.js");
const { unfinished } = require("../../understanding/wordRules/followUp.js");
const { normalise } = require("../../understanding/wordRules/text.js");

/** An empty transcript goes to the model. */
class EmptyTurn {
  get name() {
    return "EmptyTurn";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (turn.text) return null;
    return new Verdict(this.name, "empty transcript", [COUNTER.REFUSED_SHORT]);
  }
}

/**
 * A turn too short to match on meaning ("thank you") is not looked up, unless short turns are
 * on and the server's decision engine vouches for what it caches.
 */
class TooShort {
  get name() {
    return "TooShort";
  }

  get floor() {
    return false;
  }

  // Asks the server only when it must (a short turn, short turns on): then a promise.
  check(turn) {
    if (!turn.isShort) return null;
    const verdict = new Verdict(this.name, "transcript too short to match safely", [COUNTER.REFUSED_SHORT]);
    if (!turn.call.shortTurns) return verdict;
    return Promise.resolve(turn.call.engineVouches()).then((vouches) => (vouches ? null : verdict));
  }
}

/**
 * A cut-off question ("do you deliver on") is close in meaning to a full one but asks something
 * else: never served a stored answer, never stored.
 */
class CutOff {
  get name() {
    return "CutOff";
  }

  get floor() {
    return false;
  }

  check(turn) {
    if (!unfinished(turn.text)) return null;
    return new Verdict(this.name, "the turn was cut off mid-question", [COUNTER.REFUSED_SHORT]);
  }
}

// The RegisteredFiller rule (stage 1, question; operational).
const FILLER_ROUTE = "filler";
const FILLER_REASON = "registered filler, answered without a lookup or a model";

/**
 * A turn the app registered a filler for ("hello") is answered with it at once: no lookup and no
 * model. `fillers` is the session's own Map (normalised trigger to reply), read live.
 */
class RegisteredFiller {
  constructor({ fillers = new Map() } = {}) {
    // The session passes its own Map, read live; a plain object (in tests) is copied once.
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

module.exports = { EmptyTurn, TooShort, CutOff, RegisteredFiller };
