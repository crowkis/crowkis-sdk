"use strict";

const { CallState } = require("../state/callState.js");
const { FrameReading } = require("./frameReading.js");

/**
 * Adapter: reads a voice turn through an understander (LLMUnderstander over the app's `complete`
 * function, or any other). The model sees the turn, the call's facts (what earlier frames
 * remembered) and the turns in which the caller told it something (the same model already read them
 * as they were said), so it can say which of them change this answer. The stated turns are masked
 * (capitals, numbers, emails), not anonymised: plug in the app's own model, the one that already hears the call.
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
