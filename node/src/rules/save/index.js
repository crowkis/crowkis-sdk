"use strict";

// The save rules, grouped by category.

const { EmptyAnswer, NoKey, NonAnswer, NotShareable, TaintedCall, ToolResult } = require("./nothingToSave.js");
const {
  CallerIdentifier,
  DeclaredValue,
  PersonalTemplate,
  PromptCallerDetails,
  VoiceActionClaim,
  VoicePrivateWord,
} = require("./callerSpecific.js");

module.exports = {
  CallerIdentifier,
  DeclaredValue,
  EmptyAnswer,
  NoKey,
  NonAnswer,
  NotShareable,
  PersonalTemplate,
  PromptCallerDetails,
  TaintedCall,
  ToolResult,
  VoiceActionClaim,
  VoicePrivateWord,
};
