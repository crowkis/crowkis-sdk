"use strict";

// The question rules, grouped by category.

const { CutOff, EmptyTurn, RegisteredFiller, TooShort } = require("./shape.js");
const { OwnRecords } = require("./personal.js");
const { CallContextTaint, FollowUpWithoutContext, PrivateChain, VoiceStatedFacts } = require("./context.js");

module.exports = {
  CallContextTaint,
  CutOff,
  EmptyTurn,
  FollowUpWithoutContext,
  OwnRecords,
  PrivateChain,
  RegisteredFiller,
  TooShort,
  VoiceStatedFacts,
};
