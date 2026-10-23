"use strict";

const { CONFIDENCE_FLOOR } = require("./frameReading.js");
const { FUNCTION, stem, toks } = require("./frameWords.js");
const { HIGH_RISK_FACT_TYPES, highRisk } = require("./wordRules/highRisk.js");

/**
 * A stated turn ("my car was hit") may be left out of a shared question only when the model is sure
 * of the turn (not abstaining, at or above the confidence floor) and tags the fact as not changing
 * this answer, and only when neither the stated words nor the model's type say allergy, medication,
 * pregnancy or age (the floor). Late, failed, unsure or silent: the fact counts.
 */
class FactRelevanceCheck {
  constructor({ confidenceFloor = CONFIDENCE_FLOOR } = {}) {
    this._confidenceFloor = confidenceFloor;
  }

  /** The model says, sure of it, that `stated` does not change the answer to this turn. */
  irrelevant(stated, frame) {
    if (!frame || frame.abstain || frame.confidence < this._confidenceFloor || highRisk(stated)) return false;
    const statedStems = FactRelevanceCheck._contentStems(stated);
    const about = (frame.factRelevance || [])
      .filter((f) => [...FactRelevanceCheck._contentStems(f.fact)].some((s) => statedStems.has(s)));
    return about.length > 0 && !about.some((f) => f.changesAnswer || HIGH_RISK_FACT_TYPES.has(f.type));
  }

  static _contentStems(text) {
    return new Set(toks(text).filter((w) => !FUNCTION.has(w) && w.length > 2).map(stem));
  }
}

module.exports = { FactRelevanceCheck };
