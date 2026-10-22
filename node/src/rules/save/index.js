"use strict";

// The save rules, one per file.

module.exports = {
  ...require("./callerIdentifier.js"),
  ...require("./declaredValue.js"),
  ...require("./emptyAnswer.js"),
  ...require("./noKey.js"),
  ...require("./nonAnswer.js"),
  ...require("./notShareable.js"),
  ...require("./personalTemplate.js"),
  ...require("./promptCallerDetails.js"),
  ...require("./taintedCall.js"),
  ...require("./toolResult.js"),
};
