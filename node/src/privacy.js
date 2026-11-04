"use strict";

// The SDK's privacy word rules, by public, stable names, for apps and tools that reuse them
// (@crowkis/client/privacy). These names do not change when the SDK's internals move.

const { SLOT, abstract, fill } = require("./understanding/wordRules/answers.js");
const { isContextDependent } = require("./understanding/wordRules/followUp.js");
const { leaks, isPersonal } = require("./understanding/wordRules/personal.js");
const { CONTEXT_BOUND_THRESHOLD } = require("./understanding/wordRules/text.js");

module.exports = { CONTEXT_BOUND_THRESHOLD, SLOT, abstract, fill, isContextDependent, isPersonal, leaks };
