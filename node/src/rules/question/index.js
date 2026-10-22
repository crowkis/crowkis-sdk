"use strict";

// The question rules, one per file.

module.exports = {
  ...require("./aboutSomeone.js"),
  ...require("./callContextTaint.js"),
  ...require("./cutOff.js"),
  ...require("./emptyTurn.js"),
  ...require("./followUpWithoutContext.js"),
  ...require("./identifyingDetails.js"),
  ...require("./lostDetail.js"),
  ...require("./noQuestion.js"),
  ...require("./notGeneral.js"),
  ...require("./ownRecords.js"),
  ...require("./privateChain.js"),
  ...require("./questionNamesCaller.js"),
  ...require("./registeredFiller.js"),
  ...require("./statedFacts.js"),
  ...require("./taskStep.js"),
  ...require("./toldDetailDropped.js"),
  ...require("./tooShort.js"),
  ...require("./uncertainFrame.js"),
  ...require("./ungrounded.js"),
  ...require("./unresolvedReference.js"),
  ...require("./untaggedName.js"),
  ...require("./urgentTurn.js"),
  ...require("./urgentWords.js"),
};
