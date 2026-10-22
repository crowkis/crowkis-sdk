"use strict";

// The question rules, one per file.

module.exports = {
  ...require("./callContextTaint.js"),
  ...require("./cutOff.js"),
  ...require("./emptyTurn.js"),
  ...require("./followUpWithoutContext.js"),
  ...require("./ownRecords.js"),
  ...require("./privateChain.js"),
  ...require("./tooShort.js"),
};
