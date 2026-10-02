"""Pipecat processors for CallSession (turn understanding v2.2, part 5).

    stt -> user aggregator -> gate -> llm -> writeback -> tts -> audio -> output

    from crowkis.integrations.pipecat_call import call_processors
    gate, writeback, audio = call_processors(session, voice="sarvam/bulbul:v3/priya", sample_rate=24000)

All decisions live in CallBridge (framework-free, unit-tested); these classes only move
Pipecat frames in and out. The 0.5.2 processors (crowkis.integrations.pipecat) are unchanged.
Needs ``pipecat-ai``.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional

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
)
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor

from ..session import CallSession
from .call_bridge import CallBridge


class CallGate(FrameProcessor):
    def __init__(self, bridge: CallBridge):
        super().__init__()
        self.bridge = bridge

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            messages = list(frame.context.messages)
            tools = getattr(frame.context, "tools", None)
            decision = await asyncio.to_thread(self.bridge.on_context, messages, tools)
            if decision.action == "play_audio":
                frame.context.add_message({"role": "assistant", "content": decision.text})
                await self.push_frame(TTSAudioRawFrame(decision.audio, self.bridge.sample_rate, 1))
            elif decision.action == "speak_text":
                frame.context.add_message({"role": "assistant", "content": decision.text})
                await self.push_frame(TTSSpeakFrame(decision.text))
            else:
                context = frame.context
                if decision.messages != messages:
                    context = LLMContext(messages=decision.messages, tools=decision.tools)
                await self.push_frame(LLMContextFrame(context=context))
            return
        if isinstance(frame, InterruptionFrame):
            self.bridge.on_interruption()
        await self.push_frame(frame, direction)


class CallWriteBack(FrameProcessor):
    def __init__(self, bridge: CallBridge):
        super().__init__()
        self.bridge = bridge
        self._parts: Optional[list] = None

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._parts = []
        elif isinstance(frame, LLMTextFrame) and self._parts is not None:
            self._parts.append(frame.text)
        elif isinstance(frame, InterruptionFrame):
            self._parts = None
        elif isinstance(frame, LLMFullResponseEndFrame) and self._parts is not None:
            answer, self._parts = "".join(self._parts).strip(), None
            await self.push_frame(frame, direction)
            await asyncio.to_thread(self.bridge.on_answer, answer)
            return
        await self.push_frame(frame, direction)


class CallAudio(FrameProcessor):
    def __init__(self, bridge: CallBridge):
        super().__init__()
        self.bridge = bridge

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSAudioRawFrame) and direction == FrameDirection.DOWNSTREAM:
            self.bridge.on_tts_audio(frame.audio)
        elif isinstance(frame, BotStoppedSpeakingFrame):
            await asyncio.to_thread(self.bridge.on_bot_stopped)
        await self.push_frame(frame, direction)


def call_processors(session: CallSession, *, voice: str, sample_rate: int, **bridge_kwargs: Any):
    """The three processors on one bridge: ``(gate, writeback, audio)``."""
    bridge = CallBridge(session, voice=voice, sample_rate=sample_rate, **bridge_kwargs)
    return CallGate(bridge), CallWriteBack(bridge), CallAudio(bridge)


__all__ = ["CallGate", "CallWriteBack", "CallAudio", "call_processors"]
