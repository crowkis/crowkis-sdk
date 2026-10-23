"use strict";

const { CallState } = require("../../callstate.js");
const { FrameReading } = require("./frameReading.js");

/**
 * Adapter: reads a voice turn through an understander (LLMUnderstander over the app's `complete`
 * function, or any other). The model sees the turn alone, never the caller's earlier words, so
 * nothing else the caller said crosses to the provider.
 */
class LLMClassifier {
  constructor(understander) {
    this._understander = understander;
  }

  /** The model's reading of the turn. */
  async classify(text) {
    return new FrameReading(await this._understander.understand(text, new CallState()));
  }
}

module.exports = { LLMClassifier };
