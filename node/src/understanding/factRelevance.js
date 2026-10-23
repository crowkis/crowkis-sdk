"use strict";

const { CONFIDENCE_FLOOR } = require("./frameReading.js");
const { FUNCTION, stem, toks } = require("./frameWords.js");
const { HIGH_RISK_FACT_TYPES, highRisk } = require("./wordRules/highRisk.js");

// Where a stated turn holds a second fact: "going to Goa and my husband has a heart condition", "with my son who uses a wheelchair".
const CLAUSE_BREAK = /[,;.!?]|\b(?:and|but|also|plus|aur|y|with|who|whose|which|because|since|so|while|after)\b/i;

/**
 * A stated turn ("my car was hit") may be left out of a shared question only when the model is sure
 * of the turn (not abstaining, at or above the confidence floor) and tags the fact as not changing
 * this answer, and only when neither the stated words nor the model's type say allergy, medication,
 * pregnancy or age (the floor). Late, failed, unsure or silent: the fact counts. Each clause of a stated
 * turn is a fact of its own and needs its own "does not change" entry.
 */
class FactRelevanceCheck {
  constructor({ confidenceFloor = CONFIDENCE_FLOOR } = {}) {
    this._confidenceFloor = confidenceFloor;
  }

  /** The model says, sure of it, that `stated` does not change the answer to this turn. */
  irrelevant(stated, frame) {
    if (!frame || frame.abstain || frame.confidence < this._confidenceFloor || highRisk(stated)) return false;
    return FactRelevanceCheck._clauses(stated).every((clause) => FactRelevanceCheck._clauseIrrelevant(clause, frame));
  }

  static _clauseIrrelevant(clause, frame) {
    const stems = FactRelevanceCheck._contentStems(clause);
    const about = (frame.factRelevance || [])
      .filter((f) => [...FactRelevanceCheck._contentStems(f.fact)].some((s) => stems.has(s)));
    return about.length > 0 && !about.some((f) => f.changesAnswer || HIGH_RISK_FACT_TYPES.has(f.type));
  }

  /** The parts of a stated turn that say something (at least one content word). */
  static _clauses(stated) {
    const parts = stated.split(new RegExp(CLAUSE_BREAK.source, "gi")).filter((part) => part && FactRelevanceCheck._contentStems(part).size);
    return parts.length ? parts : [stated];
  }

  static _contentStems(text) {
    return new Set(toks(text).filter((w) => !FUNCTION.has(w) && w.length > 2).map(stem));
  }
}

module.exports = { FactRelevanceCheck };
