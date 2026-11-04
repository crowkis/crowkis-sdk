"use strict";

// The question rules, grouped by category.

const {
  CutOff,
  EmptyTurn,
  NoQuestion,
  NotGeneral,
  RegisteredFiller,
  TaskStep,
  TooShort,
  UncertainFrame,
  Ungrounded,
} = require("./shape.js");
const { AboutSomeone, IdentifyingDetails, OwnRecords, QuestionNamesCaller, UntaggedName } = require("./personal.js");
const {
  CallContextTaint,
  FollowUpWithoutContext,
  LostDetail,
  PrivateChain,
  StatedFacts,
  ToldDetailDropped,
  UnresolvedReference,
  VoiceStatedFacts,
} = require("./context.js");
const { UrgentTurn, UrgentWords } = require("./urgent.js");

module.exports = {
  AboutSomeone,
  CallContextTaint,
  CutOff,
  EmptyTurn,
  FollowUpWithoutContext,
  IdentifyingDetails,
  LostDetail,
  NoQuestion,
  NotGeneral,
  OwnRecords,
  PrivateChain,
  QuestionNamesCaller,
  RegisteredFiller,
  StatedFacts,
  TaskStep,
  ToldDetailDropped,
  TooShort,
  UncertainFrame,
  Ungrounded,
  UnresolvedReference,
  UntaggedName,
  UrgentTurn,
  UrgentWords,
  VoiceStatedFacts,
};
