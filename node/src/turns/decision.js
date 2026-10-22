"use strict";

// TurnDecision: what a voice session decided for one turn.

class TurnDecision {
  constructor(action, { text = null, audio = null, confidence = 0, reason = "", rule = null } = {}) {
    this.action = action;
    this.text = text;
    this.audio = audio;
    this.confidence = confidence;
    this.reason = reason;
    // The rule behind the action (null for a confident hit), and after record() the rule
    // that kept the answer out of the cache (null when it was stored). Names are the v4
    // rule names, so a decision can be traced to the one check that made it.
    this.rule = rule;
    this.saveRule = null;
    // For a model turn: what the model must read, and whether its answer is shared.
    // null means "the whole call", and then the answer is never shared.
    this.messages = null;
    this.cacheable = false;
    // Which turn of the call this is; an answer recorded for an older turn is dropped.
    this.turn = 0;
    // After answer(): whether the model's answer was stored, and if not, why.
    this.stored = false;
    this.notStored = "";
    // Not enumerable: read through `empty`, never set by callers or copied out with the decision.
    Object.defineProperty(this, "_empty", { value: false, writable: true, enumerable: false });
    Object.defineProperty(this, "_audioShareable", { value: false, writable: true, enumerable: false });
    // Set by decide(): the session that made it (a WeakRef, so a kept decision never
    // keeps a call alive) and, for a model turn, what the caller said, so record()
    // takes a decision only from its own session, and only once. Not enumerable, so a
    // logged or serialised decision never carries them; the caller's words are dropped
    // once recorded.
    Object.defineProperty(this, "_session", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_said", { value: null, writable: true, enumerable: false });
    Object.defineProperty(this, "_recorded", { value: false, writable: true, enumerable: false });
  }

  /** Whether the spoken audio of this answer may go to the shared audio cache: not for an answer filled with this caller's values. */
  get audioShareable() {
    return this._audioShareable;
  }

  get servedFromCache() {
    return this.action === "serve";
  }

  get servedFromFiller() {
    return this.action === "filler";
  }

  get needsModel() {
    return this.action === "infer";
  }

  /** After answer(): the model was asked and said nothing (the action stays "infer"); retry, or speak a fallback. */
  get empty() {
    return this._empty;
  }

  toString() {
    return (
      `TurnDecision('${this.action}', confidence=${this.confidence.toFixed(4)}, ` +
      `reason='${this.reason}')`
    );
  }
}

module.exports = { TurnDecision };
