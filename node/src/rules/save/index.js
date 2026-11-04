"use strict";

// The save rules, grouped by category.

const {
  ChatEmptyAnswer,
  ChatNonAnswer,
  ChatToolResult,
  EmptyAnswer,
  NoKey,
  NonAnswer,
  NotShareable,
  TaintedCall,
  ToolResult,
} = require("./nothingToSave.js");
const {
  ActionClaim,
  AttributeNotInKey,
  CallerIdentifier,
  ChatCallerIdentifier,
  ChatPromptDetails,
  DeclaredValue,
  IdentifyingAnswer,
  PersonalTemplate,
  PrivateWord,
  PromptCallerDetails,
  VoiceActionClaim,
  VoicePrivateWord,
} = require("./callerSpecific.js");

module.exports = {
  ActionClaim,
  AttributeNotInKey,
  CallerIdentifier,
  ChatCallerIdentifier,
  ChatEmptyAnswer,
  ChatNonAnswer,
  ChatPromptDetails,
  ChatToolResult,
  DeclaredValue,
  EmptyAnswer,
  IdentifyingAnswer,
  NoKey,
  NonAnswer,
  NotShareable,
  PersonalTemplate,
  PrivateWord,
  PromptCallerDetails,
  TaintedCall,
  ToolResult,
  VoiceActionClaim,
  VoicePrivateWord,
};
