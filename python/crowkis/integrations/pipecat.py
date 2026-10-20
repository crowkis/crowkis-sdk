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
           later context settles it, and dropped if none does. A tool that never answers
           stops holding answers once the caller has moved on twice. An answer cut off by
           a barge-in is never stored or attached to later words.
audio      stores the spoken audio of an answer the cache shares, so the next hit skips
           the TTS too. A new answer's clip waits for the write-back's ruling: it is
           stored only when the answer itself was saved word for word, and, on a server
           whose decision engine holds answers until it vouches for them, not until the
           answer is first served from the cache. A clip is never kept for an answer
           that is not shared: a tool's answer, a late one or one that is held.

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
import collections
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
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..agent import _store_later, _tts_key  # noqa: F401  (kept importable from here)
from ..client import CrowkisError  # noqa: F401  (kept importable from here)
from ..voice import VoiceSession, _words  # noqa: F401  (_words kept importable from here)
from ..voice_turns import (  # noqa: F401  (the shared layer; names kept importable from here)
    _HUNG_AFTER,
    _MAX_TOOLS,
    _RUNS_AHEAD,
    _WAITING,
    TTS_TOOL,
    AnswerPairing,
    AudioClips,
    _field,
    _last_user,
    _remember,
    _tool_context,
)

Report = Optional[Callable[[dict], Awaitable[Optional[Frame]]]]

# The model asked for a tool: its answer to the turn comes in the response after the result.
# Which of these frames exists depends on the Pipecat version.
_TOOL_CALLS = tuple(
    getattr(_frames, name) for name in ("FunctionCallsStartedFrame", "FunctionCallInProgressFrame")
    if hasattr(_frames, name)
)
_TOOL_CANCELS = tuple(getattr(_frames, name) for name in ("FunctionCallCancelFrame",) if hasattr(_frames, name))
_TOOL_RESULTS = tuple(getattr(_frames, name) for name in ("FunctionCallResultFrame",) if hasattr(_frames, name))
# The words a TTS run speaks, where the TTS reports them.
_TTS_TEXT = getattr(_frames, "TTSTextFrame", None)


def _runs_llm(result: Frame) -> bool:
    """Whether a tool's result makes Pipecat run the LLM again: only a non-empty result,
    and only if neither its properties nor the frame say ``run_llm=False``."""
    if not getattr(result, "result", None):
        return False
    properties = getattr(result, "properties", None)
    run_llm = getattr(properties, "run_llm", None)
    if run_llm is None:
        run_llm = getattr(result, "run_llm", None)
    return run_llm is not False


class CrowkisAudioCache(AudioClips, FrameProcessor):
    """Pipecat frames to the shared AudioClips events (crowkis.voice_turns)."""

    def __init__(self, session: VoiceSession, sample_rate: int):
        super().__init__()
        self._init_clips(session, sample_rate)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self.interrupted()
        elif isinstance(frame, TTSStartedFrame):
            # A new answer starts a new clip. A cached clip the gate replayed has no
            # TTSStartedFrame/TTSStoppedFrame around it, so without this it would be
            # stored as the start of the next answer. One per answer, not per sentence.
            self.tts_started()
        elif _TTS_TEXT is not None and isinstance(frame, _TTS_TEXT):
            self.tts_text(getattr(frame, "text", "") or "")
        elif isinstance(frame, TTSAudioRawFrame):
            self.tts_audio(frame.audio)
        elif isinstance(frame, TTSStoppedFrame):
            await self.tts_stopped()
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
            # A tool's answer is coming, not the caller's. Queued and pushed with nothing in
            # between, so the queue keeps the order in which the LLM receives contexts.
            settle = self.writeback.queue_context(messages)
            await self.push_frame(frame)
            if settle:
                await self.writeback._settle(True)
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
        # A served answer filled with this caller's values never uses the shared audio cache.
        shared_audio = decision.audio_shareable
        audio = None if decision.needs_model or not shared_audio else await self._audio.get(decision.text)
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
            # Served from the cache, so already shared (and vouched for, on a server
            # that holds answers): its clip may be kept. Its run is reserved in stream
            # order when the frame passes the write-back.
            if shared_audio:
                self._audio.vouch(decision.text)
            await self.push_frame(TTSSpeakFrame(decision.text))


class CrowkisWriteBack(AnswerPairing, FrameProcessor):
    """Pipecat frames to the shared AnswerPairing events (crowkis.voice_turns)."""

    def __init__(
        self, session: VoiceSession, gate: CrowkisGate, audio: CrowkisAudioCache, *, on_answer: Report = None
    ):
        super().__init__()
        self._init_pairing(session, gate, audio, on_answer)
        gate.writeback = self

    async def _report_answer(self, info: dict) -> None:
        await _report(self, self._on_answer, info)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame) and direction == FrameDirection.UPSTREAM:
            # A context sent back up to the LLM, normally with a tool's result: queued and
            # pushed with nothing in between, then any held answer is settled.
            settle = self.queue_context(list(frame.context.messages))
            await self.push_frame(frame, direction)
            if settle:
                await self._settle(True)
            return
        elif isinstance(frame, LLMFullResponseStartFrame):
            await self.response_start()
        elif isinstance(frame, TTSSpeakFrame):
            self.speak_requested(frame.text)
        elif isinstance(frame, LLMTextFrame) and self._parts is not None:
            self.response_text(frame.text)
        elif _TOOL_CALLS and isinstance(frame, _TOOL_CALLS):
            self.tool_call()
        elif (_TOOL_CANCELS and isinstance(frame, _TOOL_CANCELS)) or (
            _TOOL_RESULTS and isinstance(frame, _TOOL_RESULTS) and not _runs_llm(frame)
        ):
            self.tools_done()  # no answer will follow these tools
            await self.push_frame(frame, direction)  # forwarded first; the report can be slow
            await self._settle(True)
            return
        elif _TOOL_RESULTS and isinstance(frame, _TOOL_RESULTS):
            self.tool_result()
        elif isinstance(frame, InterruptionFrame):
            self.interrupted()
            await self.push_frame(frame, direction)  # forwarded first; the report can be slow
            await self._settle(False)
            return
        elif isinstance(frame, LLMFullResponseEndFrame) and self._parts is not None:
            todo = await self.response_end()
            if todo is not None:
                await self.push_frame(frame, direction)
                await self._record(*todo)
                return
        await self.push_frame(frame, direction)


async def _report(processor: FrameProcessor, callback: Report, info: dict) -> None:
    if callback is None:
        return
    frame: Any = await callback(info)
    if frame is not None:
        if isinstance(frame, TTSSpeakFrame) and isinstance(processor, CrowkisWriteBack):
            # Pushed below the write-back (a spoken fallback, say): its run still gets a
            # slot, and no clip is kept. The gate's frames pass the write-back, which reserves them.
            processor._audio.reserve()
        await processor.push_frame(frame)


def crowkis_processors(
    session: VoiceSession, *, sample_rate: int, on_turn: Report = None, on_answer: Report = None
):
    """The three processors, wired to one session: ``(gate, writeback, audio)``."""
    audio = CrowkisAudioCache(session, sample_rate)
    gate = CrowkisGate(session, audio, on_turn=on_turn)
    return gate, CrowkisWriteBack(session, gate, audio, on_answer=on_answer), audio


__all__ = ["CrowkisGate", "CrowkisWriteBack", "CrowkisAudioCache", "crowkis_processors"]
