"use strict";

// The word rules: fixed English word and phrase checks that read a caller's turn or a model's
// answer, one module per theme. Every name is re-exported here.

module.exports = {
  ...require("./text.js"),
  ...require("./phrases.js"),
  ...require("./urgent.js"),
  ...require("./personal.js"),
  ...require("./identifiers.js"),
  ...require("./followUp.js"),
  ...require("./callContext.js"),
  ...require("./answers.js"),
  ...require("./promptDetails.js"),
  ...require("./highRisk.js"),
};
