"use strict";

const CACHE_ROUTE = "cache";

/**
 * What the cache returned for a turn's key, typed once at the lookup: its route ("cache" when confident
 * enough to speak), the answer text, the confidence, and the flags the server's decision engine set (an
 * exact match, vouched for, a commitment such as a price or a policy). Immutable.
 */
class Hit {
  constructor({ route, answer = null, confidence = 0, exact = false, vouched = false, commitment = false, unjudged = false }) {
    Object.assign(this, { route, answer, confidence, exact, vouched, commitment, unjudged });
    Object.freeze(this);
  }

  /** Built once from Agent.ask's result. */
  static fromAgent(hit) {
    return new Hit({
      route: hit.route, answer: hit.answer ?? null, confidence: hit.confidence ?? 0, exact: Boolean(hit.exact),
      vouched: Boolean(hit.vouched), commitment: Boolean(hit.commitment), unjudged: Boolean(hit.unjudged),
    });
  }

  get isConfident() {
    return this.route === CACHE_ROUTE;
  }
}

module.exports = { CACHE_ROUTE, Hit };
