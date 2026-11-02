"use strict";

const { isThenable } = require("./turnCore.js");
const { leansOn } = require("../understanding/wordRules/index.js");
const { VoiceTurn } = require("./voiceTurn.js");
const { unnamed } = require("../understanding/chatDetails.js");

/**
 * Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite unless an
 * understander is plugged in). The rewrite is kept only when `rewriteCheck` accepts it; the call's
 * state remembers what was made of each turn. `segment` is where the call's answers are looked up
 * (null: no segment). The default slots answer at once, and so does read(); only a plugged-in
 * model's promise is awaited.
 */
class VoiceReader {
  constructor({ classifier, rewriter, rewriteCheck, state, call, segment }) {
    this._classifier = classifier;
    this._rewriter = rewriter;
    this._rewriteCheck = rewriteCheck;
    this._state = state;
    this._call = call;
    this._segment = segment;
  }

  read(said, turn) {
    const text = typeof said === "string" ? said.trim() : "";
    // The stated turns too, so the model can tag each as changing this answer or not (VD5).
    const reading = this._classifier.classify(text, [...this._state.facts, ...this._state.stated.map((t) => unnamed(t, this._state.privateRaw))]);
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
    this._state.noteReading(text, reading, rewritten);
    const chain = this._call.chain();
    if (leansOn(text, (chain || [""]).slice(-1)[0])) this._state.readFollowUp.add(text); // keyed with the turn it leans on (T21)
    return new VoiceTurn(said, this._call, reading, rewritten, { segment: this._segment, number: turn });
  }
}

module.exports = { VoiceReader };
