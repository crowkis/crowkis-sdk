"use strict";

// The SDK's privacy word rules, by public, stable names, for apps and tools that reuse them
// (@crowkis/client/privacy). These names do not change when the SDK's internals move.

const {
  CONTEXT_BOUND_THRESHOLD, SLOT, abstract, fill, isContextDependent, isPersonal, leaks,
} = require("./understanding/wordRules/index.js");

module.exports = { CONTEXT_BOUND_THRESHOLD, SLOT, abstract, fill, isContextDependent, isPersonal, leaks };
