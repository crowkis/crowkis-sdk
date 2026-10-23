"use strict";

const { CallState } = require("../state/callState.js");
const { FrameReading } = require("./frameReading.js");

/**
 * Adapter: keys a shareable turn on the understander's stand-alone, de-identified question. When the
 * classifier's reading already carries the model's frame (LLMClassifier over the same understander),
 * that frame is reused and the model is asked once per turn.
 */
class LLMRewriter {
  constructor(understander) {
    this._understander = understander;
  }

  /** The model's question for a turn that may be shared, else null (the caller's words). */
  async rewrite(text, reading) {
    if (reading.isPersonal) return null;
    if (reading instanceof FrameReading) return reading.question;
    return new FrameReading(await this._understander.understand(text, new CallState())).question;
  }
}

module.exports = { LLMRewriter };
