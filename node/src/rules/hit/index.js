"use strict";

// The hit rules, one per file.

module.exports = {
  ...require("./commitmentRewording.js"),
  ...require("./confidenceBar.js"),
  ...require("./differentQuestion.js"),
  ...require("./piiPlaceholder.js"),
  ...require("./screenOnlyAnswer.js"),
  ...require("./shortTurnUnvouched.js"),
  ...require("./templateSlotMissing.js"),
};
