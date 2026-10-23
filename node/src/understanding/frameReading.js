"use strict";

// The frame kind a voice call may share: the same answer for every caller.
const SHAREABLE_KIND = "general";
// A turn that only means something next to the turn before it.
const FOLLOW_UP_KIND = "dialogue";
// Below this the frame is a guess, and a guess is read as private (Chat's rule checker uses the same floor).
const CONFIDENCE_FLOOR = 0.6;

/**
 * What a model made of a turn, as the voice rules read it. Anything but a confident, general turn
 * about no one in particular reads as personal: a weak or unsure model costs cache hits, never
 * privacy. `frame` is kept so the rewriter reuses it instead of asking the model again.
 */
class FrameReading {
  constructor(frame) {
    this.frame = frame;
  }

  /** Not a confident, general question: never shared. */
  get isPersonal() {
    const frame = this.frame;
    return frame.kind !== SHAREABLE_KIND || frame.abstain || frame.urgent || frame.subject !== "none" ||
      frame.confidence < CONFIDENCE_FLOOR || frame.identifyingTexts.length > 0;
  }

  /** The model needed the call so far to read it. */
  get isContextDependent() {
    return this.frame.usesState || this.frame.kind === FOLLOW_UP_KIND;
  }

  /** The stand-alone question to look the turn up with, only for a turn that may be shared. */
  get question() {
    return this.isPersonal ? null : this.frame.question;
  }
}

module.exports = { FrameReading, CONFIDENCE_FLOOR };
