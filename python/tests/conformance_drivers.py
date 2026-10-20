"""The adapters, each driven through tests/conformance.py's scenarios.

A driver's ``call(store, turns, agent_id)`` plays one call (a new session) and returns,
per turn, whether the LLM and the TTS were called, what the caller heard and how long it
took. ``active()`` sets up what the framework needs for a whole scenario. ``supported``
is False when the framework is not installed."""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import List

import crowkis

from conformance import PCM, RATE, Counts, Heard, fake_tts


def _audio_of(text: str) -> bytes:
    """A stand-in TTS's audio: the text itself, so a replayed clip says what it was of."""
    data = text.encode("utf-8")
    return data + b"\x00" * (len(data) % 2)


def _text_of(audio: bytes) -> str:
    return audio.rstrip(b"\x00").decode("utf-8", "replace")


def _llm_stream(counts: Counts, pieces):
    def llm(messages):
        counts.llm += 1
        counts.read.append(messages)
        yield from pieces

    return llm


class CustomLoop:
    """A hand-written loop on VoiceSession.respond(): cached audio is played, otherwise the
    text is streamed into the app's TTS; a barge-in calls cancel()."""

    name = "custom loop, sync (VoiceSession.respond)"
    supported = True

    def active(self):
        return contextlib.nullcontext()

    async def call(self, store, turns, agent_id) -> List[Heard]:
        return await asyncio.to_thread(self._call, store, turns, agent_id)

    def _call(self, store, turns, agent_id):
        counts = Counts()
        session = crowkis.voice_session(client=store, agent_id=agent_id, voice="v", synthesise=fake_tts(counts))
        out = []
        try:
            for turn in turns:
                llm0, tts0 = counts.llm, counts.tts
                started = time.perf_counter()
                stream = session.respond(turn["say"], _llm_stream(counts, turn["reply"]), private=bool(turn.get("tool")))
                parts, spoke = [], False
                if stream.decision.audio:
                    parts.append(stream.decision.text)  # the cached clip is played: no TTS
                else:
                    for index, piece in enumerate(stream):
                        if turn.get("barge_in_after") is not None and index >= turn["barge_in_after"]:
                            session.cancel()  # the caller talked over the answer
                            break
                        spoke = True
                        parts.append(piece)
                stream.close()
                counts.tts += spoke
                out.append(Heard(counts.llm > llm0, counts.tts > tts0, "".join(parts), (time.perf_counter() - started) * 1000))
        finally:
            session.agent.close()
        return out


class AsyncCustomLoop:
    """The same loop on AsyncVoiceSession.respond()."""

    name = "custom loop, async (AsyncVoiceSession.respond)"
    supported = True

    def active(self):
        return contextlib.nullcontext()

    async def call(self, store, turns, agent_id) -> List[Heard]:
        counts = Counts()
        session = crowkis.async_voice_session(client=store, agent_id=agent_id, voice="v", synthesise=fake_tts(counts))
        out = []
        try:
            for turn in turns:
                llm0, tts0 = counts.llm, counts.tts
                started = time.perf_counter()

                async def llm(messages, pieces=turn["reply"]):
                    counts.llm += 1
                    for piece in pieces:
                        await asyncio.sleep(0)
                        yield piece

                stream = await session.respond(turn["say"], llm, private=bool(turn.get("tool")))
                parts, spoke = [], False
                if stream.decision.audio:
                    parts.append(stream.decision.text)
                else:
                    index = 0
                    async for piece in stream:
                        if turn.get("barge_in_after") is not None and index >= turn["barge_in_after"]:
                            session.cancel()
                            break
                        spoke = True
                        parts.append(piece)
                        index += 1
                await stream.close()
                counts.tts += spoke
                out.append(Heard(counts.llm > llm0, counts.tts > tts0, "".join(parts), (time.perf_counter() - started) * 1000))
        finally:
            await session.close()
        return out


# -- Pipecat ----------------------------------------------------------------------------

try:
    from pipecat.frames.frames import (
        FunctionCallsStartedFrame, InterruptionFrame, LLMContextFrame, LLMFullResponseEndFrame,
        LLMFullResponseStartFrame, LLMTextFrame, TTSAudioRawFrame, TTSSpeakFrame, TTSStartedFrame,
        TTSStoppedFrame, TTSTextFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.tests.utils import SleepFrame, run_test

    from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS
except ImportError:  # pragma: no cover - pipecat-ai not installed
    run_test = None
    FrameProcessor = object


class _PipecatLLM(FrameProcessor):
    """A streaming LLM service: its reply piece by piece, or first a tool call."""

    def __init__(self, counts, pieces, tool):
        super().__init__()
        self.counts, self.pieces, self.tool = counts, pieces, tool

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if not isinstance(frame, LLMContextFrame):
            await self.push_frame(frame, direction)
            return
        self.counts.llm += 1
        messages = frame.context.get_messages()
        await self.push_frame(LLMFullResponseStartFrame())
        if self.tool and not any(m.get("role") == "tool" for m in messages):
            await self.push_frame(FunctionCallsStartedFrame(function_calls=[]))
        else:
            for piece in self.pieces:
                await self.push_frame(LLMTextFrame(piece))
                await asyncio.sleep(0.03)
        await self.push_frame(LLMFullResponseEndFrame())


class _PipecatTTS(FrameProcessor):
    sample_rate = RATE

    def __init__(self, counts):
        super().__init__()
        from types import SimpleNamespace

        self.counts = counts
        self._settings = SimpleNamespace(voice="v")
        self._text = []

    async def _speak(self, text):
        self.counts.tts += 1
        await self.push_frame(TTSStartedFrame())
        await self.push_frame(TTSTextFrame(text, aggregated_by="sentence"))
        await self.push_frame(TTSAudioRawFrame(_audio_of(text), self.sample_rate, 1))
        await self.push_frame(TTSStoppedFrame())

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMFullResponseStartFrame):
            self._text = []
        elif isinstance(frame, LLMTextFrame):
            self._text.append(frame.text)
            return
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._text:
                await self._speak("".join(self._text))
            self._text = []
        elif isinstance(frame, TTSSpeakFrame):
            await self._speak(frame.text)
            return
        elif isinstance(frame, InterruptionFrame):
            self._text = []
        await self.push_frame(frame, direction)


class _Heard(FrameProcessor):
    """What reaches the caller: the text of each run of audio, or for a cached clip
    replayed on its own, what the clip says."""

    def __init__(self):
        super().__init__()
        self.texts, self.audio = [], []

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, TTSTextFrame):
            self.texts.append(frame.text)
        elif isinstance(frame, TTSAudioRawFrame):
            self.audio.append(frame.audio)
        await self.push_frame(frame, direction)

    def said(self) -> str:
        return " ".join(self.texts) if self.texts else _text_of(b"".join(self.audio))


def _tool_messages(question):
    return [{"role": "user", "content": question},
            {"role": "assistant", "content": "", "tool_calls": [{"id": "t1", "type": "function",
                                                                 "function": {"name": "weather", "arguments": "{}"}}]},
            {"role": "tool", "tool_call_id": "t1", "content": "sunny, 22 degrees"}]


class PipecatDriver:
    """CrowkisLLM(service) and CrowkisTTS(service) in a real Pipecat pipeline."""

    name = "Pipecat (CrowkisLLM + CrowkisTTS)"
    supported = run_test is not None

    def active(self):
        return contextlib.nullcontext()

    async def call(self, store, turns, agent_id) -> List[Heard]:
        out, history = [], []
        session = crowkis.voice_session(client=store, agent_id=agent_id)
        for turn in turns:
            counts = Counts()
            heard = _Heard()
            llm = CrowkisLLM(_PipecatLLM(counts, turn["reply"], bool(turn.get("tool"))), session=session)
            pipeline = Pipeline([llm, CrowkisTTS(_PipecatTTS(counts), llm=llm), heard])
            history = history + [{"role": "user", "content": turn["say"]}]
            frames = [LLMContextFrame(context=LLMContext(messages=list(history)))]
            if turn.get("tool"):
                frames += [SleepFrame(0.2), LLMContextFrame(context=LLMContext(messages=_tool_messages(turn["say"])))]
            if turn.get("barge_in_after") is not None:
                frames += [SleepFrame(0.03 * turn["barge_in_after"] + 0.01), InterruptionFrame()]
            frames.append(SleepFrame(0.3))  # the answer and its audio settle
            started = time.perf_counter()
            await run_test(pipeline, frames_to_send=frames)
            ms = (time.perf_counter() - started) * 1000 - 300 - (200 if turn.get("tool") else 0)
            said = heard.said()
            out.append(Heard(counts.llm > 0, counts.tts > 0, said, ms))
            history.append({"role": "assistant", "content": said})
        session.agent.close()
        return out


# -- LiveKit ----------------------------------------------------------------------------

try:
    from livekit import rtc
    from livekit.agents import Agent as LiveKitAgent, llm as lk_llm
    from livekit.agents.voice.agent import ModelSettings

    from crowkis.integrations.livekit import CrowkisVoice
except ImportError:  # pragma: no cover - livekit-agents not installed
    LiveKitAgent = None


class _LiveKitFakes:
    def __init__(self, counts):
        from types import SimpleNamespace

        self.counts = counts
        self.pieces: list = []
        self.tool = False
        self.tts = SimpleNamespace(sample_rate=RATE, num_channels=1, voice="v")

    async def llm_node(self, chat_ctx):
        self.counts.llm += 1
        if self.tool and not any(i.type == "function_call_output" for i in chat_ctx.items):
            yield lk_llm.ChatChunk(id="c", delta=lk_llm.ChoiceDelta(role="assistant", tool_calls=[
                lk_llm.FunctionToolCall(name="weather", arguments="{}", call_id="t1")]))
            return
        for piece in self.pieces:
            await asyncio.sleep(0)
            yield piece

    async def tts_node(self, text):
        said = "".join([piece async for piece in text])
        if said.strip():
            self.counts.tts += 1
        for _ in range(2):
            yield rtc.AudioFrame(PCM, RATE, 1, len(PCM) // 2)


class LiveKitDriver:
    """class Assistant(CrowkisVoice, Agent) on real livekit-agents types; the agent's own
    LLM and TTS nodes are the stand-ins."""

    name = "LiveKit (CrowkisVoice)"
    supported = LiveKitAgent is not None

    @contextlib.contextmanager
    def active(self):
        from unittest import mock

        async def llm_node(agent, chat_ctx, tools, model_settings):
            async for chunk in agent._conformance.llm_node(chat_ctx):
                yield chunk

        async def tts_node(agent, text, model_settings):
            async for frame in agent._conformance.tts_node(text):
                yield frame

        with mock.patch.multiple(LiveKitAgent.default, llm_node=llm_node, tts_node=tts_node):
            yield

    async def call(self, store, turns, agent_id) -> List[Heard]:
        counts = Counts()
        fakes = _LiveKitFakes(counts)
        session = crowkis.voice_session(client=store, agent_id=agent_id, voice="v")

        class Assistant(CrowkisVoice, LiveKitAgent):
            pass

        agent = Assistant(instructions="You are Acme's assistant.", crowkis=session)
        agent._conformance = fakes
        agent._crowkis_tts = lambda: fakes.tts
        items = [lk_llm.ChatMessage(role="system", content=["You are Acme's assistant."])]
        out = []
        for turn in turns:
            llm0, tts0 = counts.llm, counts.tts
            fakes.pieces, fakes.tool = list(turn["reply"]), bool(turn.get("tool"))
            items = items + [lk_llm.ChatMessage(role="user", content=[turn["say"]])]
            started = time.perf_counter()
            if turn.get("barge_in_after") is not None:
                said = await self._barge_in(agent, lk_llm.ChatContext(list(items)), turn["barge_in_after"])
            else:
                if turn.get("tool"):
                    await self._reply(agent, lk_llm.ChatContext(list(items)))  # the model calls the tool
                    items = items + [
                        lk_llm.FunctionCall(call_id="t1", name="weather", arguments="{}"),
                        lk_llm.FunctionCallOutput(call_id="t1", name="weather", output="sunny", is_error=False)]
                said = await self._reply(agent, lk_llm.ChatContext(list(items)))
            out.append(Heard(counts.llm > llm0, counts.tts > tts0, said, (time.perf_counter() - started) * 1000))
            items = items + [lk_llm.ChatMessage(role="assistant", content=[said or "..."])]
        await asyncio.to_thread(session.agent.close)
        return out

    @staticmethod
    def _text(chunk):
        return chunk if isinstance(chunk, str) else (chunk.delta.content or "" if chunk.delta else "")

    async def _reply(self, agent, chat_ctx):
        """One reply, as LiveKit runs it: llm_node's text into tts_node."""
        pieces = [self._text(c) async for c in agent.llm_node(chat_ctx, [], ModelSettings())]

        async def text():
            for piece in pieces:
                yield piece

        [frame async for frame in agent.tts_node(text(), ModelSettings())]
        return "".join(pieces).strip()

    async def _barge_in(self, agent, chat_ctx, after):
        """The caller talks over the reply: LiveKit stops reading it and closes it."""
        stream = agent.llm_node(chat_ctx, [], ModelSettings())
        pieces = []
        for _ in range(after):
            pieces.append(self._text(await stream.__anext__()))
        await stream.aclose()
        return "".join(pieces).strip()


DRIVERS = [CustomLoop(), AsyncCustomLoop(), PipecatDriver(), LiveKitDriver()]
