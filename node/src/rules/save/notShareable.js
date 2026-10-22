"use strict";

// The NotShareable rule (stage 3, save).

const { Verdict } = require("../../turns/verdict.js");

const KEPT = "kept";

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
    return new Verdict(this.name, "kept to this call: the answer depends on what this caller said", ["notShareable"], KEPT);
  }
}

module.exports = { NotShareable };
