"use strict";

// Commitment policies: how a cached commitment (a price, a refund, a policy) may be spoken. A Strategy per
// voiceSession({ commitments }) setting: serve any match, only the same question, or never.

const COMMITMENT_POLICIES = Object.freeze({
  serve: () => true,
  exact: (hit) => hit.exact,
  never: () => false,
});

module.exports = { COMMITMENT_POLICIES };
