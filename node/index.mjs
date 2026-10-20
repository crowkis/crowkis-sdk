// The package for ES modules: `import { VoiceSession, Agent } from "@crowkis/client"`.
//
// index.js is CommonJS and loads its voice parts lazily through getters, which Node's
// ES module loader cannot see as named exports. This names every one of them, and gives
// the very same objects require() does (one copy of each class, never two).
// test-packaging.js fails if index.js gains an export that is not named here.
//
// Naming them reads every getter, so an ES module import loads agent.js, voice.js and
// realtime.js at once (require() still loads them on first use). They only define
// classes and constants when loaded.
import crowkis from "./index.js";

export default crowkis;
export const {
  Crowkis,
  CrowkisClient,
  CrowkisAdmin,
  CrowkisError,
  CrowkisGrpcClient,
  loadCrowkisGrpc,
  Agent,
  VoiceSession,
  TurnDecision,
  VoiceResponse,
  voiceSession,
  warmFromCalls,
  RealtimeAdapter,
  RealtimeGate,
} = crowkis;
