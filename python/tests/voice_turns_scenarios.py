"""Event scenarios for the shared voice adapter layer (crowkis.voice_turns).

Each scenario is a list of plain events, the same ones a framework adapter feeds the
layer. run_events() plays them through AudioClips + AnswerPairing with a small gate
(the Pipecat gate's own rules); run_pipecat() plays the same events through the Pipecat
processors as frames. Both must end the same, and the result is saved to
fixtures/voice-turns-scenarios.json for the Node port (node/voiceTurns.js) to match.

Regenerate the file after a deliberate change:  CROWKIS_UPDATE_FIXTURES=1 python -m pytest tests/test_voice_turns.py
"""

from __future__ import annotations

import base64
import collections
import json
from pathlib import Path

from crowkis import Agent, CacheHit, VoiceSession
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice_turns import AnswerPairing, AudioClips

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "voice-turns-scenarios.json"
RATE = 16000
CLIP = base64.b64encode(b"\x01\x02" * 160).decode()

Q_REFUND = "what is your refund policy"
Q_RESET = "how do I reset my password"
Q_WEATHER = "what is the weather in paris today"
Q_HOURS = "what are your opening hours"
A_REFUND = "Refunds take five business days."
A_RESET = "Open settings, then security."


def _tool_context(question, result="sunny, 22 degrees"):
    return [
        {"role": "user", "content": question},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
                                                              "function": {"name": "weather", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "t1", "content": result},
    ]


def _answer(*pieces):
    return [{"ev": "start"}] + [{"ev": "text", "t": p} for p in pieces] + [{"ev": "end"}]


SCENARIOS = [
    {"name": "a shared answer is saved",
     "events": [{"ev": "caller", "said": Q_REFUND}, *_answer("Refunds take ", "five business days.")]},
    {"name": "a personal answer stays in the call",
     "events": [{"ev": "caller", "said": "my order 48213 has not arrived where is it"},
                *_answer("Order 48213 left the depot this morning.")]},
    {"name": "Hinglish general question is saved",
     "events": [{"ev": "caller", "said": "refund kitne din mein milta hai"}, *_answer("Paanch din mein.")]},
    {"name": "a barge-in drops the answer in progress",
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": "Refunds "},
                {"ev": "interrupt"}, {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security.")]},
    {"name": "a tool's answer is kept to the call",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "tool_context", "messages": _tool_context(Q_WEATHER)},
                *_answer("It is sunny and 22 degrees in Paris.")]},
    {"name": "a held answer is settled by the tool's context",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security."),
                {"ev": "tool_context", "messages": _tool_context(Q_WEATHER)},
                *_answer("It is sunny in Paris.")]},
    {"name": "a held answer is dropped when the caller moves on",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security."),
                {"ev": "caller", "said": Q_HOURS}, *_answer("We open at nine.")]},
    {"name": "a tool that never answers is taken as hung, then re-armed by its result",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security."),
                {"ev": "caller", "said": Q_HOURS}, *_answer("We open at nine."),
                {"ev": "caller", "said": Q_REFUND}, *_answer(A_REFUND),
                {"ev": "tool_result"}, *_answer("It is sunny in Paris after all.")]},
    {"name": "tools done settles a held answer as the caller's",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security."),
                {"ev": "tools_done"}]},
    {"name": "two responses with no context between them while a tool is in flight",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer("Open settings, then security."),
                *_answer("It is sunny.")]},
    {"name": "a context the caller did not say is never paired",
     "events": [{"ev": "other_context"}, *_answer("Sorry, could you repeat that?")]},
    {"name": "an empty response",
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "end"}]},
    {"name": "a served answer's clip is kept, then replayed",
     "seed": {Q_REFUND: A_REFUND},
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}, {"ev": "bot_stopped"},
                {"ev": "caller", "said": Q_REFUND}]},
    {"name": "a clip whose run said something else is never kept",
     "seed": {Q_REFUND: A_REFUND},
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "tts_start"},
                {"ev": "tts_text", "t": "Something else entirely."},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
    {"name": "a new answer's clip waits for the ruling, then is kept",
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": A_REFUND},
                {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND}, {"ev": "tts_audio", "b64": CLIP},
                {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "an untrusted run the TTS did not report is never kept",
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": A_REFUND},
                {"ev": "tts_start"}, {"ev": "tts_audio", "b64": CLIP}, {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "a personal answer's clip is never kept",
     "events": [{"ev": "caller", "said": "my order 48213 has not arrived where is it"}, {"ev": "start"},
                {"ev": "text", "t": "Order 48213 left the depot."}, {"ev": "tts_start"},
                {"ev": "tts_text", "t": "Order 48213 left the depot."}, {"ev": "tts_audio", "b64": CLIP},
                {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "a filler answers and its run is spoken",
     "options": {"fillers": {"hello": "Hi, how can I help?"}},
     "events": [{"ev": "caller", "said": "hello"}, {"ev": "tts_start"}, {"ev": "tts_text", "t": "Hi, how can I help?"},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
    {"name": "a run named with expect() is trusted by its order", "framework_free": True,
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "expect", "t": A_REFUND, "shareable": True},
                {"ev": "tts_start"}, {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
    {"name": "expect() replaces a trusted run that never started", "framework_free": True,
     "events": [{"ev": "expect", "t": "An answer never spoken.", "shareable": True},
                {"ev": "expect", "t": A_REFUND, "shareable": True}, {"ev": "tts_start"},
                {"ev": "tts_text", "t": A_REFUND}, {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
    {"name": "a gate with no queue pairs with its current question", "framework_free": True, "no_queue": True,
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": A_REFUND},
                {"ev": "tts_start"}, {"ev": "tts_audio", "b64": CLIP}, {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "too many runs reserved: no clip until a barge-in resets the order",
     "seed": {Q_REFUND: A_REFUND},
     "events": [*[{"ev": "speak", "t": f"Notice {n}."} for n in range(17)],
                {"ev": "caller", "said": Q_REFUND}, {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}, {"ev": "interrupt"},
                {"ev": "caller", "said": Q_REFUND}, {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
    {"name": "while the decision engine holds answers a new answer's clip is not kept", "holds": True,
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": A_REFUND},
                {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND}, {"ev": "tts_audio", "b64": CLIP},
                {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "with the Voice add-on a served answer's clip goes to the server's audio cache", "addon": True,
     "seed": {Q_REFUND: A_REFUND},
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "tts_start"}, {"ev": "tts_text", "t": A_REFUND},
                {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}, {"ev": "bot_stopped"},
                {"ev": "caller", "said": Q_REFUND}]},
    {"name": "a tool result that does not run the model settles a held answer",
     "events": [{"ev": "caller", "said": Q_WEATHER}, {"ev": "start"}, {"ev": "tool_call"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, *_answer(A_RESET), {"ev": "tool_result_no_llm"}]},
    {"name": "an empty tool_calls list is not a tool context",
     "events": [{"ev": "caller", "said": Q_REFUND},
                {"ev": "tool_context", "messages": [{"role": "user", "content": Q_REFUND},
                                                    {"role": "assistant", "content": "", "tool_calls": []}]},
                *_answer(A_REFUND)]},
    {"name": "an empty response releases its run, and the next run gets its own clip",
     "events": [{"ev": "caller", "said": Q_HOURS}, {"ev": "start"}, {"ev": "end"},
                {"ev": "caller", "said": Q_RESET}, {"ev": "start"}, {"ev": "text", "t": A_RESET},
                {"ev": "tts_start"}, {"ev": "tts_text", "t": A_RESET}, {"ev": "tts_audio", "b64": CLIP},
                {"ev": "end"}, {"ev": "tts_stop"}]},
    {"name": "a Devanagari question is never shared",
     "events": [{"ev": "caller", "said": "\u092e\u0947\u0930\u093e \u0930\u093f\u092b\u0902\u0921 \u0915\u092c \u0906\u090f\u0917\u093e"},
                *_answer("\u092a\u093e\u0901\u091a \u0926\u093f\u0928 \u092e\u0947\u0902\u0964")]},
    {"name": "a fallback spoken after a barge-in keeps its own run",
     "events": [{"ev": "caller", "said": Q_REFUND}, {"ev": "start"}, {"ev": "text", "t": "Refunds"},
                {"ev": "interrupt"}, {"ev": "speak", "t": "Sorry, go ahead."}, {"ev": "tts_start"},
                {"ev": "tts_text", "t": "Sorry, go ahead."}, {"ev": "tts_audio", "b64": CLIP}, {"ev": "tts_stop"}]},
]


class SceneStore:
    """The server: shared answers matched on the exact question, and the basic audio cache."""

    def __init__(self, seed=None):
        self.shared = dict(seed or {})
        self.tool = {}
        self.writes = []
        self.tool_writes = []
        self.tenant = None
        self.fail_soft = False

    def cget_hit(self, query, **kwargs):
        found = None if kwargs.get("template") else self.shared.get(query)
        if found is None:
            return None
        return CacheHit(response=found.encode(), similarity=0.99, ttl_remaining=600,
                        matched_key=b"k", confidence=0.99, hit_type="semantic")

    def cset(self, query, response, *, ttl=None, tenant=None, template=False):
        self.writes.append([query, response, bool(template)])
        if not template:
            self.shared[query] = response

    def ctoolget(self, tool, key, *, tenant=None):
        return self.tool.get(key)

    def ctoolset(self, tool, key, value, *, ex=None, tenant=None):
        self.tool_writes.append([json.loads(key), value])
        self.tool[key] = value


class AddonStore(SceneStore):
    """A server with the Voice add-on: the audio cache keyed by text and labels."""

    def __init__(self, seed=None):
        super().__init__(seed)
        self.audio = {}
        self.audio_writes = []

    def caudioget(self, text, *labels, tenant=None):
        return self.audio.get((text,) + labels)

    def caudioset(self, text, *labels_and_clip, ex=None, ms=None, tenant=None):
        *labels, clip = labels_and_clip
        self.audio_writes.append([text, list(labels), ms])
        self.audio[(text,) + tuple(labels)] = bytes(clip)


def _session(scenario):
    store = (AddonStore if scenario.get("addon") else SceneStore)(scenario.get("seed"))
    session = VoiceSession(Agent("caller", client=store), voice="v", **scenario.get("options", {}))
    if scenario.get("holds"):
        session.agent.decides = lambda: True  # the server's decision engine holds new answers
        session.agent._holds = True
    return store, session


def _outcome(store, session, turns, reports):
    _wait_for_audio_stores()
    return {
        "turns": turns,
        "writes": store.writes,
        "clips": [[key, value] for key, value in store.tool_writes],
        "audio_clips": getattr(store, "audio_writes", []),
        "reports": [{k: (str(v) if k == "saved" else v) for k, v in r.items() if k != "messages"} for r in reports],
        "transcript": session.transcript,
    }


class _Gate:
    def __init__(self, queue=True):
        if queue:
            self.asked = collections.deque()
        self.question = ""
        self.messages = []


class _Pairing(AnswerPairing):
    def __init__(self, session, gate, audio, on_answer):
        self._init_pairing(session, gate, audio, on_answer)


class _Clips(AudioClips):
    def __init__(self, session, rate):
        self._init_clips(session, rate)


async def run_events(scenario):
    """The scenario through the shared layer, with the Pipecat gate's own rules."""
    store, session = _session(scenario)
    queue = not scenario.get("no_queue")
    gate, turns, reports = _Gate(queue), [], []

    async def on_answer(info):
        reports.append(info)

    clips = _Clips(session, RATE)
    pairing = _Pairing(session, gate, clips, on_answer)
    serving = model_turn = False
    for event in scenario["events"]:
        kind = event["ev"]
        if kind == "caller":
            said = event["said"]
            gate.question = said
            await pairing.caller_moved_on()
            decision = session.decide(said)
            shared_audio = decision.audio_shareable
            audio = None if decision.needs_model or not shared_audio else await clips.get(decision.text)
            messages = [{"role": "user", "content": said}]
            if decision.needs_model and decision.messages is not None:
                messages = decision.messages
            gate.messages = list(messages)
            turns.append([decision.action, decision.text, audio is not None])
            model_turn = decision.needs_model
            if decision.needs_model:
                if queue:
                    gate.asked.append(("caller", decision.turn, said, gate.messages))
                continue
            serving = True
            if audio:
                clips.tts_audio(audio)  # the replayed clip passes the audio processor
            else:
                if shared_audio:
                    clips.vouch(decision.text)
                pairing.speak_requested(decision.text)
        elif kind == "other_context":
            gate.question, model_turn = "", False
            gate.asked.append(None)
        elif kind == "tool_context":
            if pairing.queue_context(event["messages"]):
                await pairing._settle(True)
        elif kind == "start":
            await pairing.response_start()
        elif kind == "text":
            pairing.response_text(event["t"])
        elif kind == "end":
            todo = await pairing.response_end()
            if todo is not None:
                await pairing._record(*todo)
        elif kind == "tool_call":
            pairing.tool_call()
        elif kind in ("tools_done", "tool_result_no_llm"):
            pairing.tools_done()
            await pairing._settle(True)
        elif kind == "tool_result":
            pairing.tool_result()
        elif kind == "expect":
            clips.expect(event["t"], shareable=event.get("shareable"))
        elif kind == "interrupt":
            if serving or model_turn:
                session.cancel()
            if queue:
                gate.asked.clear()
            serving = model_turn = False
            pairing.interrupted()
            await pairing._settle(False)
            clips.interrupted()
        elif kind == "bot_stopped":
            serving = model_turn = False
        elif kind == "speak":
            pairing.speak_requested(event["t"])
        elif kind == "tts_start":
            clips.tts_started()
        elif kind == "tts_text":
            clips.tts_text(event["t"])
        elif kind == "tts_audio":
            clips.tts_audio(base64.b64decode(event["b64"]))
        elif kind == "tts_stop":
            await clips.tts_stopped()
            _wait_for_audio_stores()  # Voice add-on clips are stored in the background
        else:
            raise ValueError(kind)
    return _outcome(store, session, turns, reports)


async def run_pipecat(scenario, pc, F, LLMContext):
    """The same scenario through the Pipecat processors, as frames."""
    store, session = _session(scenario)
    turns, reports = [], []

    async def on_turn(info):
        decision = info["decision"]
        turns.append([decision.action, decision.text, info["audio_cached"]])

    async def on_answer(info):
        reports.append(info)

    gate, writeback, audio = pc.crowkis_processors(session, sample_rate=RATE, on_turn=on_turn, on_answer=on_answer)
    stages = [gate, writeback, audio]

    async def feed(frame, stage):
        processor = stages[stage]
        before = len(processor.pushed)
        await processor.process_frame(frame, "down")
        for out in processor.pushed[before:]:
            if stage + 1 < len(stages):
                await feed(out, stage + 1)

    history = []
    for event in scenario["events"]:
        kind = event["ev"]
        if kind == "caller":
            history = [{"role": "user", "content": event["said"]}]
            await feed(F.LLMContextFrame(context=LLMContext(messages=history)), 0)
        elif kind == "other_context":
            await feed(F.LLMContextFrame(context=LLMContext(messages=[
                {"role": "user", "content": Q_REFUND}, {"role": "assistant", "content": "..."},
                {"role": "system", "content": "Ask the caller to repeat."}])), 0)
        elif kind == "tool_context":
            await feed(F.LLMContextFrame(context=LLMContext(messages=event["messages"])), 0)
        elif kind == "start":
            await feed(F.LLMFullResponseStartFrame(), 1)
        elif kind == "text":
            await feed(F.LLMTextFrame(event["t"]), 1)
        elif kind == "end":
            await feed(F.LLMFullResponseEndFrame(), 1)
        elif kind == "tool_call":
            await feed(F.FunctionCallsStartedFrame(), 1)
        elif kind == "tools_done":
            await feed(F.FunctionCallCancelFrame(), 1)
        elif kind == "tool_result":
            await feed(F.FunctionCallResultFrame("sunny", True), 1)
        elif kind == "tool_result_no_llm":
            await feed(F.FunctionCallResultFrame("sunny", False), 1)
        elif kind == "interrupt":
            await feed(F.InterruptionFrame(), 0)
        elif kind == "bot_stopped":
            await feed(F.BotStoppedSpeakingFrame(), 0)
        elif kind == "speak":
            await feed(F.TTSSpeakFrame(event["t"]), 1)
        elif kind == "tts_start":
            await feed(F.TTSStartedFrame(), 2)
        elif kind == "tts_text":
            await feed(F.TTSTextFrame(event["t"]), 2)
        elif kind == "tts_audio":
            await feed(F.TTSAudioRawFrame(base64.b64decode(event["b64"]), RATE, 1), 2)
        elif kind == "tts_stop":
            await feed(F.TTSStoppedFrame(), 2)
            _wait_for_audio_stores()  # Voice add-on clips are stored in the background
        else:
            raise ValueError(kind)
    return _outcome(store, session, turns, reports)
