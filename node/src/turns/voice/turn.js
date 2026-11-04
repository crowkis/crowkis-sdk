"use strict";

// A voice turn as read (VoiceTurn, VoiceReader) and the model's answer to it (ModelAnswer).

const { unnamed } = require("../../understanding/chatDetails.js");
const { RewriteCheck } = require("../../understanding/rewriteCheck.js");
const { CONTEXT_BOUND_THRESHOLD, isNonAnswer, leansOn } = require("../../understanding/wordRules/index.js");
const { isThenable } = require("../core.js");

/**
 * What the caller said in one turn, the call it belongs to, and how it was understood: `reading`
 * is the classifier's (personal, a follow-up) and `rewritten` the rewriter's stand-alone
 * question, or null to key the turn on the caller's words. `segment` is where the call's answers
 * are looked up (null: no segment, as before); `number` is the turn's number in the call.
 */
class VoiceTurn {
  constructor(said, call, reading, rewritten = null, { segment = null, number = 0 } = {}) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.call = call;
    this.reading = reading;
    this.rewritten = rewritten;
    this.segment = segment;
    this.number = number;
    this._read = new Map();
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** Too few words to match on meaning. */
  get isShort() {
    return this._once("isShort", () => this.text.split(/\s+/).length < this.call.minWords);
  }

  /** About the caller's own records, or otherwise never shared. */
  get isPersonal() {
    return this.reading.isPersonal || this.call.isPersonal(this.text);
  }

  /** Only means something next to the turn before it. */
  get isContextDependent() {
    return this.reading.isContextDependent || this.call.isContextDependent(this.text);
  }

  /** The model's frame of the turn, or null (the word rules make none). */
  get frame() {
    return this.reading.frame ?? null;
  }

  /** The cache key: the rewritten question, else the caller's words or the chain a follow-up leans on; null without one. */
  get key() {
    return this._once("key", () => (this.rewritten !== null ? this.rewritten : this.call.contextKey(this.said, this.text)));
  }

  /**
   * What the lookup sends besides the key: a template lookup for a personal turn, the stricter
   * threshold for a follow-up or a short turn, and the segment only when there is one (with an
   * understander, kb=<version>): the default lookup is as it was.
   */
  get lookupOptions() {
    return {
      template: this.isPersonal,
      threshold: this.isContextDependent || this.isShort ? CONTEXT_BOUND_THRESHOLD : undefined,
      ...(this.segment ? { segment: this.segment } : {}),
    };
  }
}

/**
 * What the model said to a turn, with what is known about that turn when it is recorded.
 * `key` is the turn's cache key (set once the answer is known to be one), worked out before the turn joined the transcript. `private`
 * means the answer was built from a tool's result; `instructions` is the system prompt the
 * model read; `cacheable` is whether decide() let the answer be shared.
 */
class ModelAnswer {
  constructor(said, answer, key, call, { private: keep = false, instructions = null, cacheable = false } = {}) {
    this.said = said;
    this.text = typeof said === "string" ? said.trim() : "";
    this.answer = answer;
    this.key = key;
    this.call = call;
    this.private = keep;
    this.instructions = instructions;
    this.cacheable = cacheable;
    this._read = new Map();
  }

  _once(name, read) {
    if (!this._read.has(name)) this._read.set(name, read());
    return this._read.get(name);
  }

  /** The turn was about the caller's own records, by its reading or by the word rules. */
  get isPersonal() {
    return this._once("isPersonal", () => this.call.isPersonal(this.text));
  }

  /** The answer asks back or does not answer. */
  get isNonAnswer() {
    return this._once("isNonAnswer", () => isNonAnswer(this.answer));
  }
}

const REWRITE_CHECK = new RewriteCheck();

/**
 * Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite unless an
 * understander is plugged in). The rewrite is kept only when `RewriteCheck` accepts it; the call's
 * state remembers what was made of each turn. `segment` is where the call's answers are looked up
 * (null: no segment). The default slots answer at once, and so does read(); only a plugged-in
 * model's promise is awaited.
 */
class VoiceReader {
  constructor({ classifier, rewriter, state, call, segment }) {
    this._classifier = classifier;
    this._rewriter = rewriter;
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
    rewritten = REWRITE_CHECK.accept(text, reading, rewritten, this._call);
    this._state.noteReading(text, reading, rewritten);
    const chain = this._call.chain();
    if (leansOn(text, (chain || [""]).slice(-1)[0])) this._state.readFollowUp.add(text); // keyed with the turn it leans on (T21)
    return new VoiceTurn(said, this._call, reading, rewritten, { segment: this._segment, number: turn });
  }
}

module.exports = { ModelAnswer, VoiceReader, VoiceTurn };
