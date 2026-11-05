"use strict";

const { CrowkisClient } = require("./src/client/commands.js");
const { CrowkisAdmin } = require("./src/client/admin.js");
const { CrowkisError } = require("./src/client/connection.js");
const { AGENT, FILLER, PERSONAL, SHARED, TASK, TOOLS, URGENT } = require("./src/turns/results.js");

module.exports = {
  // Where a turn goes: public, stable names (@crowkis/client/privacy has the privacy word rules).
  AGENT, FILLER, PERSONAL, SHARED, TASK, TOOLS, URGENT,
  Crowkis: CrowkisClient, // idiomatic short name (like `new Redis()`)
  CrowkisClient,
  CrowkisAdmin,
  CrowkisError,
  ...require("./src/client/grpc/grpc.js"),
  get Agent() {
    return require("./src/client/agent.js").Agent;
  },
  get VoiceSession() {
    return require("./src/channels/voiceSession.js").VoiceSession;
  },
  get TurnDecision() {
    return require("./src/channels/voiceSession.js").TurnDecision;
  },
  get VoiceResponse() {
    return require("./src/channels/voiceSession.js").VoiceResponse;
  },
  get voiceSession() {
    return require("./src/channels/voiceSession.js").voiceSession;
  },
  get warmFromCalls() {
    return require("./src/channels/voiceSession.js").warmFromCalls;
  },
  get RealtimeAdapter() {
    return require("./src/channels/realtime.js").RealtimeAdapter;
  },
  get RealtimeGate() {
    return require("./src/channels/realtime.js").RealtimeGate;
  },
  // Turn understanding: a model that reads a voice turn.
  get CallState() {
    return require("./src/state/callState.js").CallState;
  },
  get TurnFrame() {
    return require("./src/understanding/model/frame.js").TurnFrame;
  },
  get LLMUnderstander() {
    return require("./src/understanding/model/understanders.js").LLMUnderstander;
  },
  get Channel() {
    return require("./src/turns/values.js").Channel;
  },
  get VOICE() {
    return require("./src/turns/values.js").VOICE;
  },
  get CHAT() {
    return require("./src/turns/values.js").CHAT;
  },
  get REALTIME() {
    return require("./src/turns/values.js").REALTIME;
  },
  get WithFallback() {
    return require("./src/understanding/model/understanders.js").WithFallback;
  },
  get LLMClassifier() {
    return require("./src/understanding/model/understanders.js").LLMClassifier;
  },
  get LLMRewriter() {
    return require("./src/understanding/model/understanders.js").LLMRewriter;
  },
};
