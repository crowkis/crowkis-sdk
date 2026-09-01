"use strict";

// Speech-to-speech turn gate — wiring Crowkis into a realtime voice API.
//
// In a cascaded voice stack there is a text completion to intercept, so Crowkis
// sits behind one base URL change. In a speech-to-speech stack there is no text
// call at all: audio goes in, audio comes out, and the bill is charged the
// moment the model decides to speak. There is still a place to stand, because
// every realtime voice API shares three primitives:
//
//   1. it emits a free transcript of the caller's speech as a server event;
//   2. it can be configured not to auto-respond when the caller stops speaking,
//      so inference happens only when the client asks for it;
//   3. the client can inject a user turn and an assistant turn into the
//      conversation history without triggering inference.
//
// So the gate is: take the free transcript, ask Crowkis, and on a hit inject the
// exchange, play the cached audio, and never send the respond event. No
// inference billed, no synthesis billed. On a miss, send the respond event and
// let the provider answer exactly as it would have without Crowkis. One
// suppressed respond event is one inference plus one synthesis avoided;
// gate.stats().suppressed is therefore the money counter.
//
// Providers spell those three primitives differently, so the names live here, in
// this file, as configuration. The realtime module contains no provider names at
// all — it only knows the shape of the exchange, never whose it is. Two shapes
// are configured below to make that concrete: shape A carries an event kind
// under a `type` key with a flat transcript field, shape B nests everything
// under a single top-level key. The same RealtimeGate drives both.
//
// Turn detection must be configured so the provider does NOT auto-create a
// response. If it auto-responds, you have paid before Crowkis ever saw the turn.
//
// Run (needs a Crowkis server; CROWKIS_HOST / CROWKIS_PORT override the default):
//
//     node examples/node_realtime_voice_agent.js

const {
  Agent,
  VoiceSession,
  RealtimeAdapter,
  RealtimeGate,
} = require("../node/index.js");

const PROVIDER_A_TRANSCRIPT_EVENT =
  "conversation.item.input_audio_transcription.completed";
const PROVIDER_A_TRANSCRIPT_FIELD = "transcript";
const PROVIDER_A_INJECT_EVENT = "conversation.item.create";
const PROVIDER_A_RESPOND_EVENT = "response.create";

const PROVIDER_B_TRANSCRIPT_EVENT = "serverContent";
const PROVIDER_B_TRANSCRIPT_FIELD = "serverContent.inputTranscription.text";
const PROVIDER_B_INJECT_EVENT = "clientContent";
const PROVIDER_B_RESPOND_EVENT = "clientContent.turnComplete";

const HOST = process.env.CROWKIS_HOST || "127.0.0.1";
const PORT = Number(process.env.CROWKIS_PORT || 6383);
const TENANT = process.env.CROWKIS_TENANT || "aud";
const VOICE = "support-desk-1";

const COST_PER_TURN_USD = 0.025;

const KNOWN_ANSWERS = {
  "what does the pro plan cost": "The pro plan is forty dollars a month.",
  "what are your opening hours": "We are open nine until five on weekdays.",
  "do you ship internationally": "Yes, we ship to most countries.",
};

const CALL_SCRIPT = [
  "what does the pro plan cost",
  "one moment",
  "what are your opening hours",
  "what is the courier collection cutoff",
  "do you ship internationally",
  "",
];

const FILLERS = { "one moment": "Sure, give me one second." };

function providerA() {
  return new RealtimeAdapter({
    transcriptEvent: PROVIDER_A_TRANSCRIPT_EVENT,
    transcriptField: PROVIDER_A_TRANSCRIPT_FIELD,
    injectEvent: PROVIDER_A_INJECT_EVENT,
    respondEvent: PROVIDER_A_RESPOND_EVENT,
  });
}

function providerB() {
  return new RealtimeAdapter({
    transcriptEvent: PROVIDER_B_TRANSCRIPT_EVENT,
    transcriptField: PROVIDER_B_TRANSCRIPT_FIELD,
    injectEvent: PROVIDER_B_INJECT_EVENT,
    respondEvent: PROVIDER_B_RESPOND_EVENT,
  });
}

function eventA(said) {
  return {
    type: PROVIDER_A_TRANSCRIPT_EVENT,
    [PROVIDER_A_TRANSCRIPT_FIELD]: said,
  };
}

function eventB(said) {
  return { [PROVIDER_B_TRANSCRIPT_EVENT]: { inputTranscription: { text: said } } };
}

async function run(label, adapter, asEvent, agent) {
  const session = new VoiceSession(agent, { voice: VOICE, fillers: FILLERS });
  const gate = new RealtimeGate(session, adapter);

  console.log(`\n--- ${label} ---`);
  for (const said of CALL_SCRIPT) {
    const outbound = await gate.handle(asEvent(said));
    const kinds = outbound.map((event) => event.type);
    let verdict;
    if (kinds.includes(adapter.respondEvent)) verdict = "forwarded to the model";
    else if (kinds.length) verdict = `served from cache: ${gate.pendingDecision.text}`;
    else verdict = "not a transcript event, ignored";
    console.log(`  caller: ${JSON.stringify(said).padEnd(45)} -> ${verdict}`);
    if (kinds.includes(adapter.respondEvent)) {
      const answer = KNOWN_ANSWERS[said];
      if (answer) await session.recordModelTurn(said, answer);
    }
  }

  const stats = gate.stats();
  console.log(`  ${JSON.stringify(stats)}`);
  console.log(`  inferences avoided: ${stats.suppressed}`);
  console.log(
    `  cost avoided: $${(stats.suppressed * COST_PER_TURN_USD).toFixed(3)}`
  );
}

async function main() {
  const agent = new Agent("realtime-voice-demo", { host: HOST, port: PORT, tenant: TENANT });
  try {
    for (const [question, answer] of Object.entries(KNOWN_ANSWERS)) {
      await agent.learn(question, answer, { ttl: 600 });
    }
    await run("shape A", providerA(), eventA, agent);
    await run("shape B", providerB(), eventB, agent);
  } finally {
    await agent.close();
  }
}

main().catch((error) => {
  console.error(error.message);
  process.exit(1);
});
