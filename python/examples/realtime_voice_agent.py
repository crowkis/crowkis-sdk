"""Speech-to-speech turn gate — wiring Crowkis into a realtime voice API.

In a cascaded voice stack there is a text completion to intercept, so Crowkis
sits behind one `base_url` change. In a speech-to-speech stack there is no text
call at all: audio goes in, audio comes out, and the bill is charged the moment
the model decides to speak. There is still a place to stand, because every
realtime voice API shares three primitives:

  1. it emits a free transcript of the caller's speech as a server event;
  2. it can be configured not to auto-respond when the caller stops speaking, so
     inference happens only when the client asks for it;
  3. the client can inject a user turn and an assistant turn into conversation
     history without triggering inference.

So the gate is: take the free transcript, ask Crowkis, and on a hit inject the
exchange, play the cached audio, and never send the respond event. No inference
billed, no synthesis billed. On a miss, send the respond event and let the
provider answer exactly as it would have without Crowkis. One suppressed respond
event is one inference plus one synthesis avoided; `gate.stats()["suppressed"]`
is therefore the money counter.

Providers spell those three primitives differently, so the names live here, in
this file, as configuration. `crowkis.realtime` contains no provider names at
all — it only knows the shape of the exchange, never whose it is. Two shapes are
configured below to make that concrete: shape A carries an event kind under a
`type` key with a flat transcript field, shape B nests everything under a single
top-level key. The same `RealtimeGate` drives both.

Turn detection must be configured so the provider does NOT auto-create a
response. If it auto-responds, you have paid before Crowkis ever saw the turn.

Run (needs a Crowkis server; CROWKIS_HOST / CROWKIS_PORT override the default):

    python3 examples/realtime_voice_agent.py
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from crowkis import Agent, RealtimeAdapter, RealtimeGate, VoiceSession

PROVIDER_A_TRANSCRIPT_EVENT = "conversation.item.input_audio_transcription.completed"
PROVIDER_A_TRANSCRIPT_FIELD = "transcript"
PROVIDER_A_INJECT_EVENT = "conversation.item.create"
PROVIDER_A_RESPOND_EVENT = "response.create"

PROVIDER_B_TRANSCRIPT_EVENT = "serverContent"
PROVIDER_B_TRANSCRIPT_FIELD = "serverContent.inputTranscription.text"
PROVIDER_B_INJECT_EVENT = "clientContent"
PROVIDER_B_RESPOND_EVENT = "clientContent.turnComplete"

HOST = os.environ.get("CROWKIS_HOST", "127.0.0.1")
PORT = int(os.environ.get("CROWKIS_PORT", "6383"))
TENANT = os.environ.get("CROWKIS_TENANT", "aud")
VOICE = "support-desk-1"

COST_PER_TURN_USD = 0.025

KNOWN_ANSWERS = {
    "what does the pro plan cost": "The pro plan is forty dollars a month.",
    "what are your opening hours": "We are open nine until five on weekdays.",
    "do you ship internationally": "Yes, we ship to most countries.",
}

CALL_SCRIPT = [
    "what does the pro plan cost",
    "one moment",
    "what are your opening hours",
    "what is the courier collection cutoff",
    "do you ship internationally",
    "",
]

FILLERS = {"one moment": "Sure, give me one second."}


def provider_a() -> RealtimeAdapter:
    return RealtimeAdapter(
        transcript_event=PROVIDER_A_TRANSCRIPT_EVENT,
        transcript_field=PROVIDER_A_TRANSCRIPT_FIELD,
        inject_event=PROVIDER_A_INJECT_EVENT,
        respond_event=PROVIDER_A_RESPOND_EVENT,
    )


def provider_b() -> RealtimeAdapter:
    return RealtimeAdapter(
        transcript_event=PROVIDER_B_TRANSCRIPT_EVENT,
        transcript_field=PROVIDER_B_TRANSCRIPT_FIELD,
        inject_event=PROVIDER_B_INJECT_EVENT,
        respond_event=PROVIDER_B_RESPOND_EVENT,
    )


def event_a(said: str) -> dict:
    return {"type": PROVIDER_A_TRANSCRIPT_EVENT, PROVIDER_A_TRANSCRIPT_FIELD: said}


def event_b(said: str) -> dict:
    return {PROVIDER_B_TRANSCRIPT_EVENT: {"inputTranscription": {"text": said}}}


def run(label: str, adapter: RealtimeAdapter, as_event, agent: Agent) -> None:
    session = VoiceSession(agent, voice=VOICE, fillers=FILLERS)
    gate = RealtimeGate(session, adapter)

    print(f"\n--- {label} ---")
    for said in CALL_SCRIPT:
        outbound = gate.handle(as_event(said))
        kinds = [event["type"] for event in outbound]
        if adapter.respond_event in kinds:
            verdict = "forwarded to the model"
        elif kinds:
            verdict = f"served from cache: {gate.pending_decision.text}"
        else:
            verdict = "not a transcript event, ignored"
        print(f"  caller: {said!r:<45} -> {verdict}")
        if adapter.respond_event in kinds:
            answer = KNOWN_ANSWERS.get(said)
            if answer:
                # A realtime model holds the whole call, so what it says is kept to this
                # call and never cached. Shared answers come from the seeded cache above.
                session.record_private_turn(said, answer)

    stats = gate.stats()
    print(f"  {stats}")
    print(f"  inferences avoided: {stats['suppressed']}")
    print(f"  cost avoided: ${stats['suppressed'] * COST_PER_TURN_USD:.3f}")


def main() -> None:
    agent = Agent("realtime-voice-demo", host=HOST, port=PORT, tenant=TENANT)
    try:
        for question, answer in KNOWN_ANSWERS.items():
            agent.learn(question, answer, ttl=600)
        run("shape A", provider_a(), event_a, agent)
        run("shape B", provider_b(), event_b, agent)
    finally:
        agent.close()


if __name__ == "__main__":
    main()
