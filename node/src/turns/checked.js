"use strict";

/**
 * A step's subject (the turn, the answer) as the next step reads it, and the objection that stops
 * the turn there, if any (null: none). As a rule chain answers, the objection may still be pending
 * (a promise) when a rule had to ask the server; TurnCore awaits only a pending one. Immutable.
 */
class Checked {
  constructor(subject, objection = null) {
    this.subject = subject;
    this.objection = objection;
    Object.freeze(this);
  }
}

/**
 * The cache's raw `hit` for a turn (null when there was none in time), the hit as the hit rules read
 * it (`cached`, null when no hit was checked), and the objection that sends the turn to the model
 * instead, if any (pending, as in Checked, until TurnCore awaits it). Immutable.
 */
class LookedUp {
  constructor(hit, cached = null, objection = null) {
    this.hit = hit;
    this.cached = cached;
    this.objection = objection;
    Object.freeze(this);
  }
}

module.exports = { Checked, LookedUp };
