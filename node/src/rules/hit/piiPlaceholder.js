"use strict";

// The PiiPlaceholder rule (stage 2, hit).

const { Verdict } = require("../../turns/verdict.js");
const { PII_PLACEHOLDER } = require("../../understanding/wordRules.js");

const PLACEHOLDER_REASON =
  "the cached answer holds a placeholder the server put in place of a caller's detail; " +
  "reading it aloud is worse than a model call";

/** An answer holding a placeholder the server put in place of a caller's detail is never read aloud. */
class PiiPlaceholder {
  get name() {
    return "PiiPlaceholder";
  }

  get floor() {
    return false;
  }

  check(cached) {
    if (!PII_PLACEHOLDER.test(cached.answer)) return null;
    return new Verdict(this.name, PLACEHOLDER_REASON, ["refusedPrivate", "inferred"]);
  }
}

module.exports = { PiiPlaceholder };
