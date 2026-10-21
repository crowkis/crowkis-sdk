"""Crowkis in front of the LLM and the TTS of a Pipecat voice pipeline.

The one-line way: wrap the two services you already have.

    from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS

    llm = CrowkisLLM(OpenAILLMService(api_key=...))       # the cache in front of the LLM
    tts = CrowkisTTS(CartesiaTTSService(voice_id=...))    # optional: replays cached audio
    Pipeline([transport.input(), stt, user_aggregator, llm, tts, transport.output(),
              assistant_aggregator])

CrowkisLLM builds a crowkis.voice_session() (server settings from the environment, live
call defaults) unless you pass ``session=``; CrowkisTTS takes the voice id and sample rate
from the TTS service and finds the CrowkisLLM ahead of it in the pipeline by itself. The
three processors below are what they are made of, and still work on their own:

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

try:  # the one-line wrappers are pipelines of their own
    from pipecat.pipeline.pipeline import Pipeline as _Pipeline
except ImportError:  # pragma: no cover - a Pipecat without nested pipelines
    _Pipeline = None

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
    _earlier_callers,
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

# A cached clip the gate plays is marked, so the audio processor never keeps it again.
_REPLAY = "crowkis_replay"


def _mark_replay(frame: Frame) -> Frame:
    meta = getattr(frame, "metadata", None)
    if isinstance(meta, dict):
        meta[_REPLAY] = True
    else:
        setattr(frame, _REPLAY, True)
    return frame


def _is_replay(frame: Frame) -> bool:
    meta = getattr(frame, "metadata", None)
    return bool((isinstance(meta, dict) and meta.get(_REPLAY)) or getattr(frame, _REPLAY, False))


def _replay_frames(text: str, audio: bytes, sample_rate: int) -> list:
    """A cached clip played like any spoken answer: a TTS run with its text, so captions and
    transcripts show it and Pipecat's assistant aggregator adds it to the context. The text
    is marked skip_tts, so the TTS passes it on without speaking it."""
    caption = None
    try:
        caption = _TTS_TEXT(text, aggregated_by="sentence")
    except TypeError:
        caption = _TTS_TEXT(text)
    caption.skip_tts = True
    frames = [TTSStartedFrame(), TTSAudioRawFrame(audio, sample_rate, 1), caption, TTSStoppedFrame()]
    push = getattr(_frames, "LLMAssistantPushAggregationFrame", None)
    if push is not None:
        # The assistant aggregator writes to the context on a response end; a replayed
        # clip has none, so ask it to write now (not when the caller next speaks).
        frames.append(push())
    return [_mark_replay(f) for f in frames]


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


def _leading_instructions(messages: list) -> list:
    """The system / developer messages before the conversation starts: the app's own
    instructions to the model."""
    leading = []
    for message in messages:
        if _field(message, "role") not in ("system", "developer"):
            break
        leading.append(message)
    return leading


def _model_context(original: Any, messages: list, chosen: list) -> Any:
    """The context the model reads on a model turn: the app's instructions, then only
    what Crowkis chose (the question, or the questions it follows on from), with the
    original context's tools and tool choice."""
    kwargs = {name: getattr(original, name) for name in ("tools", "tool_choice") if hasattr(original, name)}
    return LLMContext(messages=_leading_instructions(messages) + list(chosen), **kwargs)


class CrowkisAudioCache(AudioClips, FrameProcessor):
    """Pipecat frames to the shared AudioClips events (crowkis.voice_turns)."""

    def __init__(self, session: VoiceSession, sample_rate: int):
        super().__init__()
        self._init_clips(session, sample_rate)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.on_frame(frame)
        await self.push_frame(frame, direction)

    async def on_frame(self, frame: Frame) -> None:
        """The TTS-side frames, as AudioClips events."""
        if _is_replay(frame):
            return  # a cached clip the gate played: already kept
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
        if _START is not None and isinstance(frame, _START) and getattr(self, "_announce", False):
            # A CrowkisLLM: tell the CrowkisTTS further down which audio cache it serves.
            await self.push_frame(frame, direction)
            await self.push_frame(CrowkisLinkFrame(audio=self._audio))
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
        for said in _earlier_callers(messages):
            # History the app gave the model: what the caller told the call there counts too.
            self._session._heard(said)
        decision = await asyncio.to_thread(self._session.decide, self.question)
        gate_ms = (time.perf_counter() - started) * 1000
        # A served answer filled with this caller's values never uses the shared audio cache.
        shared_audio = decision.audio_shareable
        audio = None if decision.needs_model or not shared_audio else await self._audio.get(decision.text)
        if decision.needs_model and decision.messages is not None:
            # The full call stays in the Pipecat context; the model just doesn't read it. It
            # does read the app's own instructions (the system messages before the call)
            # and keeps its tools: these used to be dropped on every model turn. An answer
            # that repeats a detail those instructions give about this caller is never
            # shared (see VoiceSession: the instructions go with the answer when recorded).
            frame = LLMContextFrame(context=_model_context(frame.context, messages, decision.messages))
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
        if audio and _TTS_TEXT is not None:
            # Played like any spoken answer (see _replay_frames): the assistant aggregator
            # adds it to the context, once.
            for out in _replay_frames(decision.text, audio, self._audio.sample_rate):
                await self.push_frame(out)
        elif audio:
            # A Pipecat without TTSTextFrame: the answer goes into the context directly.
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
        self._llm_service: Any = None  # set by CrowkisLLM: its system_instruction is read too

    @property
    def _service_instructions(self) -> Optional[str]:
        """The LLM service's own system instruction (Pipecat setting), which the model
        reads on every turn: an answer repeating a caller's detail from it is not shared."""
        settings = getattr(self._llm_service, "_settings", None)
        instruction = getattr(settings, "system_instruction", None)
        return instruction if isinstance(instruction, str) else None

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


_START = getattr(_frames, "StartFrame", None)
_TTS_SETTINGS = getattr(_frames, "TTSUpdateSettingsFrame", None)
_SYSTEM_FRAME = getattr(_frames, "SystemFrame", Frame)


class CrowkisLinkFrame(_SYSTEM_FRAME):  # type: ignore[misc,valid-type]
    """Sent by a CrowkisLLM when the pipeline starts, so the CrowkisTTS after it finds
    the audio cache it serves without being told. Never leaves a CrowkisTTS."""

    def __init__(self, audio: Any = None):
        super().__init__()
        self.audio = audio


def _voice_of(service: Any) -> Optional[str]:
    """The voice id a Pipecat TTS service speaks with, where it says."""
    settings = getattr(service, "_settings", None)
    for value in (getattr(settings, "voice", None), getattr(service, "_voice_id", None)):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class _AudioRelay(FrameProcessor):
    """Inside a CrowkisTTS, after the TTS service: feeds the linked audio cache the
    TTS frames, and gives it the service's sample rate and voice."""

    def __init__(self, tts: Any, audio: Optional[CrowkisAudioCache] = None):
        super().__init__()
        self._tts = tts
        self._target = audio
        self._started = False
        self._owns_voice = False  # the session's voice came from this TTS, so follows it

    def _attach(self) -> None:
        audio = self._target
        if audio is None or not self._started:
            return
        rate = getattr(self._tts, "sample_rate", None)
        if isinstance(rate, int) and rate > 0:
            audio.sample_rate = rate
        session = audio._session
        voice = _voice_of(self._tts)
        if voice and (getattr(session, "_text_only", False) or self._owns_voice):
            # voice_session() made with no voice: the TTS names it, so audio is cached
            # (keyed on this voice) from now on, and follows the TTS if it changes voice.
            session.voice = voice
            session._text_only = False
            self._owns_voice = True

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, CrowkisLinkFrame):
            if self._target is None:
                self._target = frame.audio
            self._attach()
            return  # it ends here
        if _START is not None and isinstance(frame, _START):
            self._started = True  # the TTS service ahead has started: its rate is known
            self._attach()
        elif _TTS_SETTINGS is not None and isinstance(frame, _TTS_SETTINGS):
            self._attach()  # the TTS ahead has applied it: a new voice keys new clips
        elif self._target is not None:
            await self._target.on_frame(frame)
        await self.push_frame(frame, direction)


if _Pipeline is not None:

    class CrowkisLLM(_Pipeline):
        """Crowkis in front of a Pipecat LLM service: ``CrowkisLLM(OpenAILLMService(...))``.

        A cache hit is spoken without the LLM; on a miss the LLM answers as before and the
        answer is cached when it is safe to share. ``session`` is the VoiceSession to use;
        left out, one is made with crowkis.voice_session(**session_options) (server
        settings from the environment). ``on_turn`` / ``on_answer`` are the same callbacks
        as crowkis_processors(). The parts: ``.session``, ``.gate``, ``.writeback``,
        ``.audio``.
        """

        def __init__(self, service: FrameProcessor, session: Optional[VoiceSession] = None, *,
                     on_turn: Report = None, on_answer: Report = None, **session_options: Any):
            if session is not None and session_options:
                raise ValueError(
                    f"CrowkisLLM got session= and {', '.join(sorted(session_options))}: "
                    "set these on the session you pass, or leave session out"
                )
            if session is None:
                from ..voice import voice_session

                session = voice_session(**session_options)
            self.session = session
            # The sample rate is the TTS service's: CrowkisTTS sets it when the pipeline starts.
            self.audio = CrowkisAudioCache(session, sample_rate=0)
            self.gate = CrowkisGate(session, self.audio, on_turn=on_turn)
            self.gate._announce = True
            self.writeback = CrowkisWriteBack(session, self.gate, self.audio, on_answer=on_answer)
            self.writeback._llm_service = service
            self.service = service
            super().__init__([self.gate, service, self.writeback])

        # The LLM service's own calls (register_function, register_direct_function, ...)
        # work on the wrapper. Event handlers belong to the service: use
        # ``llm.service.event_handler(...)``.
        def __getattr__(self, name: str) -> Any:
            service = self.__dict__.get("service")
            if service is None or name.startswith("_"):
                raise AttributeError(name)
            return getattr(service, name)

    class CrowkisTTS(_Pipeline):
        """Cached audio for a Pipecat TTS service: ``CrowkisTTS(CartesiaTTSService(...))``.

        Place it where the TTS service was, after a CrowkisLLM. A cached answer whose audio
        is known is played without the TTS; a new answer's audio is kept once its text is
        shared. The voice id and sample rate come from the service. ``llm`` names the
        CrowkisLLM to serve; left out, the one ahead in the pipeline is found when it starts.
        """

        def __init__(self, service: FrameProcessor, llm: Optional["CrowkisLLM"] = None):
            self.service = service
            self._relay = _AudioRelay(service, llm.audio if llm is not None else None)
            super().__init__([service, self._relay])

else:  # pragma: no cover

    class CrowkisLLM:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError("CrowkisLLM needs a Pipecat with pipecat.pipeline.pipeline.Pipeline")

    class CrowkisTTS:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any):
            raise ImportError("CrowkisTTS needs a Pipecat with pipecat.pipeline.pipeline.Pipeline")


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


__all__ = ["CrowkisLLM", "CrowkisTTS", "CrowkisGate", "CrowkisWriteBack", "CrowkisAudioCache", "crowkis_processors"]
