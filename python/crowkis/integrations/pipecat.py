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
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..voice import VoiceSession, _words

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
# The words a TTS run speaks, where the TTS reports them.
_TTS_TEXT = getattr(_frames, "TTSTextFrame", None)
# Answered caller turns a tool may say nothing through before it is taken as hung, and
# how many silent tools are remembered at most.
_HUNG_AFTER = 2
_MAX_TOOLS = 4


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
    """Whether a tool's result makes Pipecat run the LLM again: only a non-empty result,
    and only if neither its properties nor the frame say ``run_llm=False``."""
    if not getattr(result, "result", None):
        return False
    properties = getattr(result, "properties", None)
    run_llm = getattr(properties, "run_llm", None)
    if run_llm is None:
        run_llm = getattr(result, "run_llm", None)
    return run_llm is not False


# Answers whose clip or ruling is still waiting for the other. One turn is in flight at
# a time; a few cover a barge-in that leaves one behind.
_WAITING = 4
# TTS runs that may be reserved ahead of the one playing.
_RUNS_AHEAD = 16


def _remember(waiting: dict, key: str, value: Any) -> None:
    waiting.pop(key, None)
    waiting[key] = value
    while len(waiting) > _WAITING:
        waiting.pop(next(iter(waiting)))


class CrowkisAudioCache(FrameProcessor):
    def __init__(self, session: VoiceSession, sample_rate: int):
        super().__init__()
        self._session = session
        self.sample_rate = sample_rate
        self._pcm = bytearray()
        # By answer text: finished clips waiting for a ruling, and rulings waiting for
        # their clip. The TTS can finish before or after the write-back has ruled.
        self._clips: dict = {}
        self._rulings: dict = {}
        # One slot per TTS run still to come, in the order the runs will happen: [text].
        # A run's audio belongs to the slot it starts with, never to whatever text was
        # named last, so a clip cannot be stored under another answer's text.
        self._runs: collections.deque = collections.deque()
        self._run: Optional[list] = None  # the slot of the TTS run in progress
        self._unsynced = False
        self._spoken: list = []  # what that run said, where the TTS reports it

    def _key(self, text: str) -> str:
        return json.dumps({"voice": self._session.voice, "text": text}, sort_keys=True)

    async def get(self, text: str) -> Optional[bytes]:
        agent = self._session.agent
        raw = await asyncio.to_thread(agent._client.ctoolget, TTS_TOOL, self._key(text), tenant=agent.tenant)
        return base64.b64decode(raw) if raw else None

    def expect(self, text: str, *, shareable: Optional[bool] = None) -> None:
        """Name the answer that the next TTS run speaks.

        ``shareable=True`` for an answer the cache just served: its clip may be stored.
        Left out for a new answer: its clip waits for ``settle``. A run named here is
        trusted by its order; naming another before it starts replaces it."""
        for waiting in [slot for slot in self._runs if slot[1]]:
            self._runs.remove(waiting)  # its run never happened: no slot is left behind
        self.reserve(text, trusted=True)
        if shareable is not None:
            _remember(self._rulings, text, shareable)

    def reserve(self, text: Optional[str] = None, *, trusted: bool = False) -> list:
        """Hold the place of a TTS run that is coming, in stream order; its text can be
        filled in later (``slot[0] = text``), before the run ends. Unless ``trusted``,
        its clip is kept only when the TTS reports having spoken that text."""
        slot = [text, trusted]
        self._runs.append(slot)
        if len(self._runs) > _RUNS_AHEAD:
            # ponytail: far more runs waiting than a call ever has; rather than guess which
            # run is which, keep no clip until a barge-in resets the order.
            self._runs.clear()
            self._unsynced = True
        return slot

    def release(self, slot: list) -> None:
        """A reserved run that will not happen (an answer with nothing to speak)."""
        if slot in self._runs:
            self._runs.remove(slot)

    def vouch(self, text: str) -> None:
        """An answer the cache served: its clip may be stored once its own run ends."""
        _remember(self._rulings, text, True)

    async def settle(self, text: str, shareable: bool) -> None:
        """The write-back's ruling on a new answer: store its clip, or drop it."""
        clip = self._clips.pop(text, None)
        if clip is None:
            _remember(self._rulings, text, shareable)
        elif shareable:
            await self._store(text, clip)

    async def _finish_clip(self) -> None:
        """The audio of a TTS run is complete: it belongs to the slot the run started with."""
        run, self._run = self._run, None
        text, clip, spoken = (run[0] if run else None), bytes(self._pcm), _words(" ".join(self._spoken))
        self._pcm, self._spoken = bytearray(), []
        if not (text and clip) or self._unsynced:
            return
        if spoken and spoken != _words(text)[:len(spoken)]:
            return  # the run said something else: never store it under this text
        if not spoken and not run[1]:
            return  # fail closed: the TTS did not say what it spoke
        ruling = self._rulings.pop(text, None)
        if ruling is None:
            _remember(self._clips, text, clip)
        elif ruling:
            await self._store(text, clip)

    async def _store(self, text: str, clip: bytes) -> None:
        agent = self._session.agent
        await asyncio.to_thread(
            agent._client.ctoolset, TTS_TOOL, self._key(text), base64.b64encode(clip).decode("ascii"),
            ex=self._session.ttl, tenant=agent.tenant,
        )

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, InterruptionFrame):
            self._pcm, self._run, self._spoken, self._unsynced = bytearray(), None, [], False
            self._runs.clear()
        elif isinstance(frame, TTSStartedFrame):
            # A new answer starts a new clip. A cached clip the gate replayed has no
            # TTSStartedFrame/TTSStoppedFrame around it, so without this it would be
            # stored as the start of the next answer. One per answer, not per sentence.
            self._pcm, self._spoken = bytearray(), []
            self._run = self._runs.popleft() if self._runs else None
        elif _TTS_TEXT is not None and isinstance(frame, _TTS_TEXT) and self._run is not None:
            self._spoken.append(getattr(frame, "text", "") or "")
        elif isinstance(frame, TTSAudioRawFrame):
            self._pcm += frame.audio
        elif isinstance(frame, TTSStoppedFrame):
            await self._finish_clip()
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
            # Served from the cache, so already shared (and vouched for, on a server
            # that holds answers): its clip may be kept. Its run is reserved in stream
            # order when the frame passes the write-back.
            self._audio.vouch(decision.text)
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
        self._moves = 0  # caller turns answered, unrecorded, while a tool said nothing
        self._hung: list = []  # tools taken as hung; a result from one re-arms it
        self._deferred: Optional[tuple] = None  # (context, answer) of a held response
        self._slot: Optional[list] = None  # the audio run reserved for the response in progress

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
            # Its TTS run, in stream order. A gate with no queue of contexts keeps the
            # original contract: the run is trusted by its order.
            self._slot = self._audio.reserve(trusted=getattr(self._gate, "asked", None) is None)
            await self._start()
        elif isinstance(frame, TTSSpeakFrame):
            self._audio.reserve(frame.text)
        elif isinstance(frame, LLMTextFrame) and self._parts is not None:
            self._parts.append(frame.text)
        elif _TOOL_CALLS and isinstance(frame, _TOOL_CALLS):
            self._calling = True
        elif (_TOOL_CANCELS and isinstance(frame, _TOOL_CANCELS)) or (
            _TOOL_RESULTS and isinstance(frame, _TOOL_RESULTS) and not _runs_llm(frame)
        ):
            self._pending.clear()  # no answer will follow these tools
            self._hung.clear()
            await self.push_frame(frame, direction)  # forwarded first; the report can be slow
            await self._settle(True)
            return
        elif _TOOL_RESULTS and isinstance(frame, _TOOL_RESULTS) and not self._pending and self._hung:
            # A tool taken as hung has answered after all: what follows is its answer.
            self._pending.append(self._hung.pop(0))
        elif isinstance(frame, InterruptionFrame):
            self._parts, self._bound, self._calling, self._held, self._slot = None, None, False, False, None
            await self.push_frame(frame, direction)  # forwarded first; the report can be slow
            await self._settle(False)
            return
        elif isinstance(frame, LLMFullResponseEndFrame) and self._parts is not None:
            answer, self._parts = "".join(self._parts).strip(), None
            bound, self._bound = self._bound, None
            calling, self._calling = self._calling, False
            slot, self._slot = self._slot, None
            if slot is not None and answer:
                slot[0] = answer  # its clip waits for the ruling below
            elif slot is not None:
                self._audio.release(slot)
            if bound is not None and calling:
                # Nothing to record until the tool's result is answered.
                if not self._pending:
                    self._moves = 0
                self._pending = (self._pending + [bound[1:]])[-_MAX_TOOLS:]
                await self._audio.settle(answer, False)
            elif bound is not None and bound[0] == "caller" and self._held:
                self._deferred = (bound, answer)
            elif bound is not None:
                await self.push_frame(frame, direction)
                await self._record(bound, answer)
                return
            else:
                await self._audio.settle(answer, False)
        await self.push_frame(frame, direction)

    def queue_context(self, messages: list) -> bool:
        """Queue a context the LLM will answer that the caller did not just say. No await:
        the caller pushes it right after. True when a held answer is now known to be the
        caller's own (the tool's answer comes from this context): settle it then."""
        if not _tool_context(messages):
            self._gate.asked.append(None)
            return False
        question, _ = _last_user(messages)
        tool = next((t for t in self._pending if t[1] == question), None)
        if tool is not None:
            self._pending.remove(tool)
        self._gate.asked.append(("tool", tool[0] if tool else None, question, messages))
        return True

    async def caller_moved_on(self) -> None:
        """A new caller turn: a held response can no longer be told apart from a tool's.
        A tool that has said nothing while two of the caller's turns were answered is
        taken as hung, so it stops holding the call's answers; a result from it later
        re-arms it."""
        if self._pending and self._deferred is not None:
            # The caller's previous turn was answered while the tool said nothing. Only such
            # turns count: a tool can still answer, without its context seen, across turns
            # that were merely asked. The queue of silent tools is capped instead.
            self._moves += 1
        if self._pending and self._moves >= _HUNG_AFTER:
            self._hung, self._pending, self._moves = self._pending[-_MAX_TOOLS:], [], 0
        await self._settle(False)

    async def _start(self) -> None:
        self._parts, self._held = [], False
        asked = getattr(self._gate, "asked", None)
        if asked is None:
            # A gate that keeps no queue of contexts: pair with its current question, as before.
            self._bound = ("caller", None, self._gate.question, self._gate.messages)
            return
        if self._deferred is not None:
            # Two responses with no context between them while a tool was in flight:
            # either could be the tool's answer, so neither is stored or paired. Between
            # them they answered the held one's context and the next one waiting (or the
            # tool's, if its context was never seen).
            if asked:
                asked.popleft()
            elif self._pending:
                self._pending.pop(0)
            self._bound = None
            await self._settle(False)
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
            return
        await self._audio.settle(deferred[1], False)
        # Reported with no question: it is never paired with a caller turn.
        await _report(self, self._on_answer, {
            "question": "", "answer": deferred[1], "messages": [], "saved": "not_saved",
            "stored": False, "not_stored": "could not be told apart from a tool's late answer",
        })

    async def _record(self, bound: tuple, answer: str) -> None:
        kind, turn, question, messages = bound
        if not question or (kind == "tool" and turn is None):
            # Only what the caller said is recorded, and only for a turn it belongs to.
            await self._audio.settle(answer, False)
            return
        # Record first, so the report can say what happened to the answer.
        if turn is None and kind == "caller":
            saved = await asyncio.to_thread(self._session._record_model_turn, question, answer)
        else:
            saved = await asyncio.to_thread(
                self._session._record_model_turn, question, answer, turn=turn, private=kind == "tool"
            )
        await self._audio.settle(answer, await asyncio.to_thread(self._clip_allowed, saved))
        stored = saved in ("saved", "template")
        await _report(self, self._on_answer, {
            "question": question, "answer": answer, "messages": messages, "saved": saved,
            "stored": stored, "not_stored": "" if stored else (getattr(saved, "why", "") or str(saved)),
        })

    def _clip_allowed(self, saved: str) -> bool:
        """Whether the spoken audio of a new answer may be kept, given what happened to
        its text. Only an answer saved word for word: a template is saved with this
        caller's values taken out, but its audio still says them. And not while the
        server's decision engine holds answers until it vouches for them: the text is
        not shared yet and may be removed, so the clip is made when it is first served."""
        if saved != "saved":
            return False
        agent = self._session.agent
        return not (agent.decides() and agent._holds)


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
