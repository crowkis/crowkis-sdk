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


# -- Bolna ------------------------------------------------------------------------------

try:
    from bolna import providers as bolna_providers
    from bolna.helpers.conversation_history import ConversationHistory
    from bolna.llms.llm import BaseLLM
    from bolna.llms.types import LatencyData, LLMStreamChunk
    from bolna.synthesizer.base_synthesizer import BaseSynthesizer

    from crowkis.integrations.bolna import register_crowkis
except ImportError:  # pragma: no cover - bolna not installed
    BaseLLM = BaseSynthesizer = object
    bolna_providers = None

BOLNA_NAME = "crowkis-conformance"
BOLNA_BASE = "crowkis-conformance-base"
BOLNA_SYNTH = "crowkis-conformance-synth"
BOLNA_QUIET_S = 0.02  # how long the synthesizer may stay silent before its audio is taken as read
BOLNA_SYSTEM = "You are Acme's assistant."
BOLNA_BUFFER = 40


class _BolnaScript:
    """What the stand-in Bolna LLM does this turn: its reply pieces, or first a tool call."""

    def __init__(self, counts):
        self.counts = counts
        self.pieces: list = []
        self.tool = False


class _BolnaInnerLLM(BaseLLM):
    """A Bolna LLM class (the registered provider's base) streaming a scripted reply as chunks."""

    def __init__(self, conformance_script=None, **kwargs):
        super().__init__(max_tokens=100, buffer_size=BOLNA_BUFFER)
        self.model = "fake"
        self.script = conformance_script
        self.cancelled = 0

    async def generate_stream(self, messages, synthesize=True, request_json=False, meta_info=None,
                              tool_choice=None, tools=None):
        self.script.counts.llm += 1
        self.script.counts.read.append(messages)
        sequence_id = (meta_info or {}).get("sequence_id")
        if self.script.tool and not any(m.get("role") == "tool" for m in messages):
            yield LLMStreamChunk(data=None, end_of_stream=True, is_function_call=True, function_name="weather")
            return
        pieces = self.script.pieces or [""]
        for index, piece in enumerate(pieces):
            await asyncio.sleep(0)
            yield LLMStreamChunk(data=piece, end_of_stream=index == len(pieces) - 1,
                                 latency=LatencyData(sequence_id=sequence_id))

    def invalidate_response_chain(self):
        pass

    def cancel_in_flight_response(self):
        self.cancelled += 1

    async def close(self):
        pass


class _BolnaInnerSynth(BaseSynthesizer):
    """A Bolna synthesizer class (mu-law, HTTP style): one packet of audio for each text pushed.
    It counts the texts it was asked to speak, which is how the driver knows the TTS was used."""

    def __init__(self, counts=None, task_manager_instance=None, voice="v", **kwargs):
        super().__init__(task_manager_instance, stream=False, buffer_size=BOLNA_BUFFER)
        self.counts = counts
        self.voice = voice

    def _get_http_audio_format(self):
        return "mulaw"

    async def push(self, message):
        if (message["data"] or "").strip():
            self.counts.tts += 1
        await super().push(message)

    async def generate(self):
        while True:
            message = await self.internal_queue.get()
            meta_info, text = message["meta_info"], message["data"]
            self._stamp_first_chunk(meta_info)
            self._stamp_end_of_stream(meta_info)
            meta_info.update(format="mulaw", text=text, text_synthesized=f"{text} ")
            self._stamp_mark_id(meta_info)
            audio = f"<{text}>".encode() if (text or "").strip() else b"\x00"
            yield {"data": audio, "meta_info": meta_info}


class _BolnaTaskManager:
    """What the adapter reads of Bolna's TaskManager: its history and task config."""

    def __init__(self):
        self.conversation_history = ConversationHistory([])
        self.task_config = {"tools_config": {"llm_agent": {"agent_type": "simple_llm_agent"}}}
        self.conversation_history.messages.append({"role": "system", "content": BOLNA_SYSTEM})

    @property
    def history(self):
        return self.conversation_history.messages

    def hear(self, text):
        self.history.append({"role": "user", "content": text})

    def commit(self, response_uid, text):
        """Bolna's commit of a reply to its history, once the audio went out."""
        self.conversation_history.append_assistant(text, response_uid=response_uid, turn_id=1)


def _chunks_text(chunks) -> str:
    return " ".join(" ".join(str(chunk.data or "").split()) for chunk in chunks).strip()


class BolnaDriver:
    """The class register_crowkis() returns, driven the way Bolna drives an LLM: each turn
    a copy of the history goes to generate_stream(synthesize=True, meta_info=...), every
    chunk is consumed, then the reply is committed to the history; a barge-in commits the
    trimmed reply and calls cancel_in_flight_response(). Each answer's text then goes to the
    call's synthesizer (a CrowkisSynthesizer around a stand-in that counts what it is asked to
    speak), so the ``tts`` expectations are checked too."""

    name = "Bolna (register_crowkis)"
    supported = bolna_providers is not None

    @contextlib.contextmanager
    def active(self):
        llms_before = dict(bolna_providers.SUPPORTED_LLM_PROVIDERS)
        synths_before = dict(bolna_providers.SUPPORTED_SYNTHESIZER_MODELS)
        bolna_providers.SUPPORTED_LLM_PROVIDERS[BOLNA_BASE] = _BolnaInnerLLM
        bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[BOLNA_SYNTH] = _BolnaInnerSynth
        try:
            yield
        finally:
            bolna_providers.SUPPORTED_LLM_PROVIDERS.clear()
            bolna_providers.SUPPORTED_LLM_PROVIDERS.update(llms_before)
            bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.clear()
            bolna_providers.SUPPORTED_SYNTHESIZER_MODELS.update(synths_before)

    async def call(self, store, turns, agent_id) -> List[Heard]:
        counts = Counts()
        script = _BolnaScript(counts)
        provider = register_crowkis(name=BOLNA_NAME, base=BOLNA_BASE, synthesizer=BOLNA_SYNTH,
                                    session_factory=lambda: crowkis.async_voice_session(
                                        client=store, agent_id=agent_id, voice="v"))
        task_manager = _BolnaTaskManager()
        llm = provider(language="en", model="fake", provider=BOLNA_NAME, conformance_script=script,
                       task_manager_instance=task_manager)
        synth = bolna_providers.SUPPORTED_SYNTHESIZER_MODELS[BOLNA_SYNTH](
            counts=counts, voice="v", task_manager_instance=task_manager)
        out = []
        try:
            for sequence, turn in enumerate(turns, start=1):
                llm0, tts0 = counts.llm, counts.tts
                script.pieces, script.tool = list(turn["reply"]), bool(turn.get("tool"))
                task_manager.hear(turn["say"])
                started = time.perf_counter()
                said, chunks, spoken_sequence = await self._turn(llm, task_manager, turn, sequence)
                ms = (time.perf_counter() - started) * 1000
                await self._speak(synth, chunks, spoken_sequence, interrupted=turn.get("barge_in_after") is not None)
                out.append(Heard(counts.llm > llm0, counts.tts > tts0, said, ms))
        finally:
            await llm.close()
        return out

    async def _turn(self, llm, task_manager, turn, sequence):
        """What the caller heard, the chunks Bolna sends on to speak, and the sequence they are for."""
        uid = f"r{sequence}"
        meta = {"sequence_id": sequence, "response_uid": uid, "origin": "transcriber", "turn_id": sequence}
        if turn.get("barge_in_after") is not None:
            return await self._barge_in(llm, task_manager, meta, turn["barge_in_after"])
        chunks = await self._consume(llm, task_manager, meta)
        spoken_sequence = sequence
        if turn.get("tool"):
            # The model asked for a tool: Bolna runs it and calls the LLM again with its result.
            task_manager.history.extend([
                {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "t1", "type": "function", "function": {"name": "weather", "arguments": "{}"}}]},
                {"role": "tool", "tool_call_id": "t1", "content": "sunny, 22 degrees"}])
            spoken_sequence = sequence + 1000
            chunks = await self._consume(llm, task_manager, dict(meta, sequence_id=spoken_sequence))
        said = _chunks_text(chunks)
        task_manager.commit(uid, said)
        return said, chunks, spoken_sequence

    @staticmethod
    async def _speak(synth, chunks, sequence, *, interrupted) -> None:
        """Bolna's task manager gives each text chunk to the synthesizer and plays what comes
        back; on a barge-in it tells the synthesizer to drop what is in flight."""
        for chunk in chunks:
            await synth.push({"data": chunk.data, "meta_info": {
                "sequence_id": sequence, "turn_id": sequence, "end_of_llm_stream": chunk.end_of_stream}})
        stream = synth.generate()
        async with contextlib.aclosing(stream):
            while True:
                try:
                    packet = await asyncio.wait_for(stream.__anext__(), BOLNA_QUIET_S)
                except (asyncio.TimeoutError, StopAsyncIteration):
                    break
                if packet["meta_info"].get("end_of_synthesizer_stream"):
                    break
        if interrupted:
            await synth.handle_interruption()

    @staticmethod
    async def _consume(llm, task_manager, meta):
        history = [dict(row) for row in task_manager.history]
        return [chunk async for chunk in llm.generate_stream(history, synthesize=True, meta_info=meta)]

    @staticmethod
    async def _barge_in(llm, task_manager, meta, after) -> str:
        """The caller talks over the reply: Bolna stops reading it, cancels, and keeps only what was spoken."""
        history = [dict(row) for row in task_manager.history]
        stream = llm.generate_stream(history, synthesize=True, meta_info=meta)
        chunks = [await stream.__anext__() for _ in range(after)]
        llm.cancel_in_flight_response()
        await stream.aclose()
        said = _chunks_text(chunks)
        task_manager.commit(meta["response_uid"], said)
        return said, chunks, meta["sequence_id"]


DRIVERS = [CustomLoop(), AsyncCustomLoop(), PipecatDriver(), LiveKitDriver(), BolnaDriver()]
