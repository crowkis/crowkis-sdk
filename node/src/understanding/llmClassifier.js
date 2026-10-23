"use strict";

const { CallState } = require("../state/callState.js");
const { FrameReading } = require("./frameReading.js");

/**
 * Adapter: reads a voice turn through an understander (LLMUnderstander over the app's `complete`
 * function, or any other). The model sees the turn and the call's de-identified facts (what earlier
 * frames remembered, never a name, a number or an earlier turn), so it can say which facts change
 * this answer.
 */
class LLMClassifier {
  constructor(understander) {
    this._understander = understander;
  }

  /** The model's reading of the turn. */
  async classify(text, facts = []) {
    return new FrameReading(await this._understander.understand(text, new CallState({ facts })));
  }
}

module.exports = { LLMClassifier };
