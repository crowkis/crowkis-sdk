"use strict";

// The save rules, one per file.

module.exports = {
  ...require("./actionClaim.js"),
  ...require("./attributeNotInKey.js"),
  ...require("./callerIdentifier.js"),
  ...require("./chatCallerIdentifier.js"),
  ...require("./chatEmptyAnswer.js"),
  ...require("./chatNonAnswer.js"),
  ...require("./chatPromptDetails.js"),
  ...require("./chatToolResult.js"),
  ...require("./declaredValue.js"),
  ...require("./emptyAnswer.js"),
  ...require("./identifyingAnswer.js"),
  ...require("./noKey.js"),
  ...require("./nonAnswer.js"),
  ...require("./notShareable.js"),
  ...require("./personalTemplate.js"),
  ...require("./privateWord.js"),
  ...require("./promptCallerDetails.js"),
  ...require("./taintedCall.js"),
  ...require("./toolResult.js"),
  ...require("./voiceActionClaim.js"),
  ...require("./voicePrivateWord.js"),
};
