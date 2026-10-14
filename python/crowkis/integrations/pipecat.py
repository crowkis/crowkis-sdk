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
writeback  hands each complete model answer to the session. An answer cut off by a
           barge-in is never stored.
audio      stores the spoken audio of an answer the cache shares, so the next hit skips
           the TTS too. A new answer's clip waits for the write-back's ruling: it is
           stored only when the answer itself was saved word for word, and, on a server
           whose decision engine holds answers until it vouches for them, not until the
           answer is first served from the cache. A clip is never kept for an answer
           that is not shared.

``on_turn`` and ``on_answer`` are optional async callbacks for the app's own reporting
(metrics, a UI). Each gets a dict; a Pipecat frame it returns is pushed downstream.

Needs ``pipecat-ai``. The Crowkis SDK is synchronous, so its calls run in a thread to
keep the event loop free.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
from typing import Any, Awaitable, Callable, Optional

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

from ..voice import VoiceSession

# Same tool name and key shape as Agent.speak(), so both share one audio cache.
TTS_TOOL = "crowkis.tts"

Report = Optional[Callable[[dict], Awaitable[Optional[Frame]]]]


# Answers whose clip or ruling is still waiting for the other. One turn is in flight at
# a time; a few cover a barge-in that leaves one behind.
_WAITING = 4


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
        self._text: Optional[str] = None
        self._pcm = bytearray()
        # By answer text: finished clips waiting for a ruling, and rulings waiting for
        # their clip. The TTS can finish before or after the write-back has ruled.
        self._clips: dict = {}
        self._rulings: dict = {}

    def _key(self, text: str) -> str:
        return json.dumps({"voice": self._session.voice, "text": text}, sort_keys=True)

    async def get(self, text: str) -> Optional[bytes]:
        agent = self._session.agent
        raw = await asyncio.to_thread(agent._client.ctoolget, TTS_TOOL, self._key(text), tenant=agent.tenant)
        return base64.b64decode(raw) if raw else None

    def expect(self, text: str, *, shareable: Optional[bool] = None) -> None:
        """Name the answer that the TTS audio about to arrive belongs to.

        ``shareable=True`` for an answer the cache just served: its clip may be stored.
        Left out for a new answer: its clip waits for ``settle``."""
        self._text = text
        if shareable is not None:
            _remember(self._rulings, text, shareable)

    async def settle(self, text: str, shareable: bool) -> None:
        """The write-back's ruling on a new answer: store its clip, or drop it."""
        clip = self._clips.pop(text, None)
        if clip is None:
            _remember(self._rulings, text, shareable)
        elif shareable:
            await self._store(text, clip)

    async def _finish_clip(self) -> None:
        """The audio of the expected answer is complete."""
        if not (self._text and self._pcm):
            return
        text, clip = self._text, bytes(self._pcm)
        self._text, self._pcm = None, bytearray()
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
            self._text, self._pcm = None, bytearray()
        elif isinstance(frame, TTSStartedFrame):
            # A new answer starts a new clip. A cached clip the gate replayed has no
            # TTSStartedFrame/TTSStoppedFrame around it, so without this it would be
            # stored as the start of the next answer. One per answer, not per sentence.
            self._pcm = bytearray()
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
        self.question = ""
        self.messages: list = []  # what the LLM reads for this turn

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            await self._answer(frame)
            return
        if isinstance(frame, InterruptionFrame) and self._serving:
            self._session.cancel()  # barge-in over a cached answer: forget that turn
        if isinstance(frame, (InterruptionFrame, BotStoppedSpeakingFrame)):
            self._serving = False
        await self.push_frame(frame, direction)

    async def _answer(self, frame: LLMContextFrame):
        last = frame.context.messages[-1]
        if last.get("role") != "user":
            # Not something the caller said, e.g. Pipecat's own "please repeat that" prompt
            # after a cut-off turn. Let the model handle it, and never cache it.
            self.question = ""
            await self.push_frame(frame)
            return
        self.question = last.get("content", "")
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

        if decision.needs_model:
            await self.push_frame(frame)
            return
        self._serving = True
        if audio:
            frame.context.add_message({"role": "assistant", "content": decision.text})
            await self.push_frame(TTSAudioRawFrame(audio, self._audio.sample_rate, 1))
        else:
            # Served from the cache, so already shared (and vouched for, on a server
            # that holds answers): its clip may be kept.
            self._audio.expect(decision.text, shareable=True)
            await self.push_frame(TTSSpeakFrame(decision.text))


class CrowkisWriteBack(FrameProcessor):
    def __init__(
        self, session: VoiceSession, gate: CrowkisGate, audio: CrowkisAudioCache, *, on_answer: Report = None
    ):
        super().__init__()
        self._session = session
        self._gate = gate
        self._audio = audio
        self._on_answer = on_answer
        self._parts: Optional[list] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._parts = []
        elif isinstance(frame, LLMTextFrame) and self._parts is not None:
            self._parts.append(frame.text)
        elif isinstance(frame, InterruptionFrame):
            self._parts = None
        elif isinstance(frame, LLMFullResponseEndFrame) and self._parts is not None and self._gate.question:
            answer, self._parts = "".join(self._parts).strip(), None
            self._audio.expect(answer)
            await self.push_frame(frame, direction)
            # Record first, so the report can say what happened to the answer.
            saved = await asyncio.to_thread(self._session._record_model_turn, self._gate.question, answer)
            await self._audio.settle(answer, await asyncio.to_thread(self._clip_allowed, saved))
            await _report(self, self._on_answer, {
                "question": self._gate.question, "answer": answer, "messages": self._gate.messages,
                "saved": saved,
            })
            return
        await self.push_frame(frame, direction)


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
        await processor.push_frame(frame)


def crowkis_processors(
    session: VoiceSession, *, sample_rate: int, on_turn: Report = None, on_answer: Report = None
):
    """The three processors, wired to one session: ``(gate, writeback, audio)``."""
    audio = CrowkisAudioCache(session, sample_rate)
    gate = CrowkisGate(session, audio, on_turn=on_turn)
    return gate, CrowkisWriteBack(session, gate, audio, on_answer=on_answer), audio


__all__ = ["CrowkisGate", "CrowkisWriteBack", "CrowkisAudioCache", "crowkis_processors"]
