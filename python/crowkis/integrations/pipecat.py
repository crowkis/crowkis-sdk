"""Crowkis in front of the LLM and the TTS of a Pipecat voice pipeline.

    stt -> user aggregator -> gate -> llm -> writeback -> tts -> audio -> output

    from crowkis.integrations.pipecat import crowkis_processors

    gate, writeback, audio = crowkis_processors(session, sample_rate=24000)
    Pipeline([transport.input(), stt, user_aggregator, gate, llm, writeback,
              tts, audio, transport.output(), assistant_aggregator])

gate       answers a turn from the cache (text, and audio when it has it). On a miss the
           LLM reads exactly ``decision.messages``: the question alone (or with the
           question before it) for an answer that is shared, the whole call for one that
           is not. Nothing else this caller said can end up inside a shared answer.
writeback  hands each complete model answer to the session with the context it was
           generated from. The LLM answers contexts in the order it receives them, and
           every context it receives passes the gate (the caller's) or the writeback
           (one sent back up after a tool's result), so each response is matched to its
           context, and each context is read: one with a tool call or result after its
           last user message is a tool's answer, never stored and never paired with a
           caller turn; it goes to the call's own transcript only while its turn is the
           current one. A caller's answer is paired with the question that is that
           context's last user message, and only while no tool is in flight: a response
           that could be either a tool's late answer or the caller's own is held until a
           later context settles it, and dropped if none does. An answer cut off by a
           barge-in is never stored or attached to later words.
audio     stores the TTS audio of each new answer, so the next hit skips the TTS too.

``on_turn`` and ``on_answer`` are optional async callbacks for the app's own reporting
(metrics, a UI). Each gets a dict; a Pipecat frame it returns is pushed downstream.
``on_answer`` says whether the answer was stored and, when not, why (``not_stored``):
an empty answer, or the server's own reason for refusing the write. An app can
return a frame from it to speak a fallback when the model said nothing.

Needs ``pipecat-ai``. The Crowkis SDK is synchronous, so its calls run in a thread to
keep the event loop free.
"""

from __future__ import annotations

import asyncio
import base64
import collections
import json
import time
from typing import Any, Awaitable, Callable, Optional

from pipecat.frames import frames as _frames
from pipecat.frames.frames import (
    BotStoppedSpeakingFrame,
    Frame,
    InterruptionFrame,
    LLMContextFrame,
    LLMFullResponseEndFrame,
    LLMFullResponseStartFrame,
    LLMTextFrame,
    TTSAudioRawFrame,
    TTSSpeakFrame,
    TTSStoppedFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..voice import VoiceSession

# Same tool name and key shape as Agent.speak(), so both share one audio cache.
TTS_TOOL = "crowkis.tts"

Report = Optional[Callable[[dict], Awaitable[Optional[Frame]]]]

# The model asked for a tool: its answer to the turn comes in the response after the result.
# Which of these frames exists depends on the Pipecat version.
_TOOL_CALLS = tuple(
    getattr(_frames, name) for name in ("FunctionCallsStartedFrame", "FunctionCallInProgressFrame")
    if hasattr(_frames, name)
)
_TOOL_CANCELS = tuple(getattr(_frames, name) for name in ("FunctionCallCancelFrame",) if hasattr(_frames, name))
_TOOL_RESULTS = tuple(getattr(_frames, name) for name in ("FunctionCallResultFrame",) if hasattr(_frames, name))


def _field(message: Any, name: str) -> Any:
    return message.get(name) if isinstance(message, dict) else getattr(message, name, None)


def _last_user(messages: list) -> tuple:
    """The last user message's text, and the messages after it."""
    for index in range(len(messages) - 1, -1, -1):
        if _field(messages[index], "role") == "user":
            return _field(messages[index], "content") or "", messages[index + 1:]
    return None, list(messages)


def _tool_context(messages: list) -> bool:
    """Whether a context carries a tool call or a tool's result after its last user message."""
    _, after = _last_user(messages)
    return any(
        _field(m, "role") in ("tool", "function") or _field(m, "tool_calls") or _field(m, "function_call")
        or _field(m, "type") in ("function_call", "function_call_output", "tool_use", "tool_result")
        for m in after
    )


def _runs_llm(result: Frame) -> bool:
    """Whether a tool's result asks the LLM for a follow-up response (Pipecat's run_llm)."""
    properties = getattr(result, "properties", None)
    run_llm = getattr(properties, "run_llm", None)
    if run_llm is None:
        run_llm = getattr(result, "run_llm", None)
    return run_llm is not False


class CrowkisAudioCache(FrameProcessor):
    def __init__(self, session: VoiceSession, sample_rate: int):
        super().__init__()
        self._session = session
        self.sample_rate = sample_rate
        self._text: Optional[str] = None
        self._pcm = bytearray()

    def _key(self, text: str) -> str:
        return json.dumps({"voice": self._session.voice, "text": text}, sort_keys=True)

    async def get(self, text: str) -> Optional[bytes]:
        agent = self._session.agent
        raw = await asyncio.to_thread(agent._client.ctoolget, TTS_TOOL, self._key(text), tenant=agent.tenant)
        return base64.b64decode(raw) if raw else None

    def expect(self, text: str) -> None:
        """Name the answer that the TTS audio about to arrive belongs to."""
        self._text = text

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self._text, self._pcm = None, bytearray()
        elif isinstance(frame, TTSAudioRawFrame):
            self._pcm += frame.audio
        elif isinstance(frame, TTSStoppedFrame) and self._text and self._pcm:
            agent = self._session.agent
            clip = base64.b64encode(self._pcm).decode("ascii")
            await asyncio.to_thread(
                agent._client.ctoolset, TTS_TOOL, self._key(self._text), clip,
                ex=self._session.ttl, tenant=agent.tenant,
            )
            self._text, self._pcm = None, bytearray()
        await self.push_frame(frame, direction)


class CrowkisGate(FrameProcessor):
    def __init__(self, session: VoiceSession, audio: CrowkisAudioCache, *, on_turn: Report = None):
        super().__init__()
        self._session = session
        self._audio = audio
        self._on_turn = on_turn
        self._serving = False
        self._model_turn = False
        self.question = ""
        self.messages: list = []  # what the LLM reads for this turn
        # One entry per context sent to the LLM, oldest first: (kind, turn, question,
        # messages) with kind "caller" or "tool", or None for one nobody can be paired
        # with. The LLM answers them in order; the writeback adds the contexts sent back
        # up after a tool's result.
        self.asked: collections.deque = collections.deque()
        self.writeback: Optional["CrowkisWriteBack"] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self._answer(frame)
            return
        if isinstance(frame, InterruptionFrame):
            if self._serving or self._model_turn:
                self._session.cancel()  # barge-in: forget that turn, and never store its answer
            self.asked.clear()
        if isinstance(frame, (InterruptionFrame, BotStoppedSpeakingFrame)):
            self._serving = False
            self._model_turn = False
        await self.push_frame(frame, direction)

    async def _answer(self, frame: LLMContextFrame):
        messages = list(frame.context.messages)
        if self.writeback is not None and _tool_context(messages):
            await self.writeback.context(messages)  # a tool's answer is coming, not the caller's
            await self.push_frame(frame)
            return
        last = messages[-1] if messages else {}
        if _field(last, "role") != "user":
            # Not something the caller said, e.g. Pipecat's own "please repeat that" prompt
            # after a cut-off turn. Let the model handle it, and never cache it.
            self.question = ""
            self._model_turn = False
            self.asked.append(None)
            await self.push_frame(frame)
            return
        self.question = _field(last, "content") or ""
        if self.writeback is not None:
            await self.writeback.caller_moved_on()
        started = time.perf_counter()
        decision = await asyncio.to_thread(self._session.decide, self.question)
        gate_ms = (time.perf_counter() - started) * 1000
        audio = None if decision.needs_model else await self._audio.get(decision.text)
        if decision.needs_model and decision.messages is not None:
            # The full call stays in the Pipecat context; the model just doesn't read it.
            frame = LLMContextFrame(context=LLMContext(messages=decision.messages))
        self.messages = list(frame.context.messages)
        await _report(self, self._on_turn, {
            "question": self.question,
            "decision": decision,
            "gate_ms": gate_ms,
            "audio_cached": audio is not None,
            "messages": self.messages,  # on a hit: what the model would have read
            "stats": self._session.stats(),
        })

        self._model_turn = decision.needs_model
        if decision.needs_model:
            self.asked.append(("caller", decision.turn, self.question, self.messages))
            await self.push_frame(frame)
            return
        self._serving = True
        if audio:
            frame.context.add_message({"role": "assistant", "content": decision.text})
            await self.push_frame(TTSAudioRawFrame(audio, self._audio.sample_rate, 1))
        else:
            self._audio.expect(decision.text)
            await self.push_frame(TTSSpeakFrame(decision.text))


class CrowkisWriteBack(FrameProcessor):
    def __init__(
        self, session: VoiceSession, gate: CrowkisGate, audio: CrowkisAudioCache, *, on_answer: Report = None
    ):
        super().__init__()
        self._session = session
        self._gate = gate
        gate.writeback = self
        self._audio = audio
        self._on_answer = on_answer
        self._parts: Optional[list] = None
        self._bound: Optional[tuple] = None  # the context the response in progress was generated from
        self._held = False  # that response could be a tool's late answer: hold it until settled
        self._calling = False  # the response in progress asked for a tool
        self._pending: list = []  # (turn, question, messages) of tool calls whose answer is still to come
        self._deferred: Optional[tuple] = None  # (context, answer) of a held response

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.UPSTREAM:
            # A context sent back up to the LLM, normally with a tool's result.
            await self.context(list(frame.context.messages))
        elif isinstance(frame, LLMFullResponseStartFrame):
            await self._start()
        elif isinstance(frame, LLMTextFrame) and self._parts is not None:
            self._parts.append(frame.text)
        elif _TOOL_CALLS and isinstance(frame, _TOOL_CALLS):
            self._calling = True
        elif (_TOOL_CANCELS and isinstance(frame, _TOOL_CANCELS)) or (
            _TOOL_RESULTS and isinstance(frame, _TOOL_RESULTS) and not _runs_llm(frame)
        ):
            self._pending.clear()  # no answer will follow these tools
            await self._settle(True)
        elif isinstance(frame, InterruptionFrame):
            self._parts, self._bound, self._calling, self._held = None, None, False, False
            await self._settle(False)
        elif isinstance(frame, LLMFullResponseEndFrame) and self._parts is not None:
            answer, self._parts = "".join(self._parts).strip(), None
            bound, self._bound = self._bound, None
            calling, self._calling = self._calling, False
            if bound is not None and calling:
                self._pending.append(bound[1:])  # nothing to record until the tool's result is answered
            elif bound is not None and bound[0] == "caller" and self._held:
                self._deferred = (bound, answer)
            elif bound is not None:
                await self.push_frame(frame, direction)
                await self._record(bound, answer)
                return
        await self.push_frame(frame, direction)

    async def context(self, messages: list) -> None:
        """A context the LLM will answer that the caller did not just say."""
        if not _tool_context(messages):
            self._gate.asked.append(None)
            return
        question, _ = _last_user(messages)
        tool = next((t for t in self._pending if t[1] == question), None)
        if tool is not None:
            self._pending.remove(tool)
        self._gate.asked.append(("tool", tool[0] if tool else None, question, messages))
        await self._settle(True)  # the tool's answer comes from this context: a held one was the caller's

    async def caller_moved_on(self) -> None:
        """A new caller turn: a held response can no longer be told apart from a tool's."""
        await self._settle(False)

    async def _start(self) -> None:
        self._parts, self._held = [], False
        asked = self._gate.asked
        if self._deferred is not None:
            # Two responses with no context between them while a tool was in flight:
            # either could be the tool's answer, so neither is stored or paired, and the
            # contexts still waiting can no longer be matched to what answers them.
            await self._settle(False)
            if self._pending:
                self._pending.pop(0)
            for index, entry in enumerate(asked):
                if entry is not None:
                    asked[index] = ("lost",) + entry[1:]
            self._bound = None
            return
        if asked:
            self._bound = asked.popleft()
        elif self._pending:
            self._bound = ("tool",) + self._pending.pop(0)  # the answer after the tool's result
        else:
            self._bound = None
        self._held = bool(
            self._bound and self._bound[0] == "caller"
            and (self._pending or any(e and e[0] == "tool" for e in asked))
        )

    async def _settle(self, answered: bool) -> None:
        """Record a held response as its caller's answer, or drop it."""
        deferred, self._deferred = self._deferred, None
        if deferred is None:
            return
        if answered:
            await self._record(*deferred)
        else:  # reported with no question: it is never paired with a caller turn
            await _report(self, self._on_answer, {
                "question": "", "answer": deferred[1], "messages": [], "stored": False,
                "not_stored": "could not be told apart from a tool's late answer",
            })

    async def _record(self, bound: tuple, answer: str) -> None:
        kind, turn, question, messages = bound
        if not question or kind == "lost" or (kind == "tool" and turn is None):
            return  # only what the caller said is recorded, and only for a turn it belongs to
        self._audio.expect(answer)
        why = await asyncio.to_thread(
            self._session._record_model_turn, question, answer, turn=turn, private=kind == "tool"
        )
        await _report(self, self._on_answer, {
            "question": question, "answer": answer, "messages": messages,
            "stored": why is None, "not_stored": why or "",
        })


async def _report(processor: FrameProcessor, callback: Report, info: dict) -> None:
    if callback is None:
        return
    frame: Any = await callback(info)
    if frame is not None:
        await processor.push_frame(frame)


def crowkis_processors(
    session: VoiceSession, *, sample_rate: int, on_turn: Report = None, on_answer: Report = None
):
    """The three processors, wired to one session: ``(gate, writeback, audio)``."""
    audio = CrowkisAudioCache(session, sample_rate)
    gate = CrowkisGate(session, audio, on_turn=on_turn)
    return gate, CrowkisWriteBack(session, gate, audio, on_answer=on_answer), audio


__all__ = ["CrowkisGate", "CrowkisWriteBack", "CrowkisAudioCache", "crowkis_processors"]
