"use strict";

const { isThenable } = require("./turnCore.js");
const { VoiceTurn } = require("./voiceTurn.js");

/**
 * Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite unless an
 * understander is plugged in). The rewrite is kept only when `rewriteCheck` accepts it; the call's
 * readings remember what was made of each turn. `segment` is where the call's answers are looked up
 * (null: no segment). The default slots answer at once, and so does read(); only a plugged-in
 * model's promise is awaited.
 */
class VoiceReader {
  constructor({ classifier, rewriter, rewriteCheck, callReadings, call, segment }) {
    this._classifier = classifier;
    this._rewriter = rewriter;
    this._rewriteCheck = rewriteCheck;
    this._callReadings = callReadings;
    this._call = call;
    this._segment = segment;
  }

  read(said, turn) {
    const text = typeof said === "string" ? said.trim() : "";
    const reading = this._classifier.classify(text, this._callReadings.facts);
    if (isThenable(reading)) return this._readLater(said, turn, text, reading);
    const rewritten = this._rewriter.rewrite(text, reading);
    if (isThenable(rewritten)) return this._readLater(said, turn, text, reading, rewritten);
    return this._turn(said, turn, text, reading, rewritten);
  }

  // A plugged-in model answered with a promise: the same steps, once it has answered.
  async _readLater(said, turn, text, reading, rewritten) {
    reading = await reading;
    if (rewritten === undefined) rewritten = this._rewriter.rewrite(text, reading);
    if (isThenable(rewritten)) rewritten = await rewritten;
    return this._turn(said, turn, text, reading, rewritten);
  }

  _turn(said, turn, text, reading, rewritten) {
    rewritten = this._rewriteCheck.accept(text, reading, rewritten, this._call);
    this._callReadings.note(text, reading, rewritten);
    return new VoiceTurn(said, this._call, reading, rewritten, { segment: this._segment, number: turn });
  }
}

module.exports = { VoiceReader };
