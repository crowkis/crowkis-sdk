"use strict";

const { fill } = require("../understanding/wordRules.js");

/**
 * What the cache returned for a turn. `started` is when the lookup began (performance.now()).
 */
class CachedAnswer {
  constructor(turn, hit, started) {
    this.turn = turn;
    this.hit = hit;
    this.started = started;
    this._answer = undefined;
  }

  /**
   * The text to speak: for a personal turn, the shared answer shape filled with this call's
   * values, or null when a slot has no value. Read only for a confident hit.
   */
  get answer() {
    if (this._answer === undefined) {
      this._answer = this.turn.isPersonal ? fill(this.hit.answer, this.turn.call.values) : this.hit.answer;
    }
    return this._answer;
  }
}

module.exports = { CachedAnswer };
