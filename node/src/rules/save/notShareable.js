"use strict";

// The NotShareable rule (stage 3, save).

const { OUTCOME } = require("../../turns/outcome.js");
const { Verdict } = require("../../turns/verdict.js");
const { COUNTER } = require("../../runtime/stats.js");

/** An answer decide() did not let be shared (the model read more than the question) stays in the call. */
class NotShareable {
  get name() {
    return "NotShareable";
  }

  get floor() {
    return false;
  }

  check(answer) {
    if (answer.cacheable) return null;
    return new Verdict(this.name, "kept to this call: the answer depends on what this caller said", [COUNTER.NOT_SHAREABLE], OUTCOME.KEPT);
  }
}

module.exports = { NotShareable };
