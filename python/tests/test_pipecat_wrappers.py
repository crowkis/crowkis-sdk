"""CrowkisLLM / CrowkisTTS: Crowkis in a Pipecat pipeline by wrapping the two services.

    llm = CrowkisLLM(OpenAILLMService(...))
    tts = CrowkisTTS(CartesiaTTSService(...))

Run through a real Pipecat pipeline (pipecat.tests.utils.run_test), with stand-in LLM and
TTS services: a miss reaches the LLM and its answer and audio are kept; the same question
again is spoken from the cache, audio and all, without the LLM or the TTS. The voice id and
sample rate come from the TTS service; the CrowkisTTS finds its CrowkisLLM by itself."""

import asyncio
import os
import unittest
from types import SimpleNamespace
from unittest import mock

try:
    from pipecat.frames.frames import (
        LLMContextFrame, LLMFullResponseEndFrame, LLMFullResponseStartFrame, LLMTextFrame,
        TTSAudioRawFrame, TTSSpeakFrame, TTSStartedFrame, TTSStoppedFrame, TTSTextFrame,
    )
    from pipecat.pipeline.pipeline import Pipeline
    from pipecat.processors.aggregators.llm_context import LLMContext
    from pipecat.processors.frame_processor import FrameProcessor
    from pipecat.tests.utils import SleepFrame, run_test

    from crowkis.integrations.pipecat import CrowkisLLM, CrowkisTTS
except ImportError:  # pragma: no cover - pipecat-ai not installed
    run_test = None
    FrameProcessor = object

import crowkis
from voice_turns_scenarios import SceneStore

QUESTION = "what is your refund policy"
ANSWER = "Refunds take five business days."
PCM = b"\x01\x02" * 320
_NAMES = ("CROWKIS_HOST", "CROWKIS_PORT", "CROWKIS_AUTH_TOKEN", "CROWKIS_TOKEN", "CROWKIS_TENANT", "CROWKIS_URL")


class FakeLLM(FrameProcessor):
    """Answers every context with one text frame, and remembers what it was asked."""

    def __init__(self, reply=ANSWER, system_instruction=None):
        super().__init__()
        self.reply = reply
        self.asked = []
        self._settings = SimpleNamespace(system_instruction=system_instruction)

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMContextFrame):
            self.asked.append(frame.context.get_messages())
            await self.push_frame(LLMFullResponseStartFrame())
            await self.push_frame(LLMTextFrame(self.reply))
            await self.push_frame(LLMFullResponseEndFrame())
        else:
            await self.push_frame(frame, direction)


class FakeTTS(FrameProcessor):
    """Speaks a response (or a TTSSpeakFrame) as one run of audio."""

    sample_rate = 16000

    def __init__(self, voice="rachel"):
        super().__init__()
        self._settings = SimpleNamespace(voice=voice)
        self.spoke = []
        self._text = []

    async def _speak(self, text):
        self.spoke.append(text)
        await self.push_frame(TTSStartedFrame())
        await self.push_frame(TTSTextFrame(text, aggregated_by="sentence"))
        await self.push_frame(TTSAudioRawFrame(PCM, self.sample_rate, 1))
        await self.push_frame(TTSStoppedFrame())

    async def process_frame(self, frame, direction):
        await super().process_frame(frame, direction)
        if isinstance(frame, LLMTextFrame):
            self._text.append(frame.text)
        elif isinstance(frame, LLMFullResponseEndFrame):
            await self.push_frame(frame, direction)
            text, self._text = "".join(self._text), []
            if text:
                await self._speak(text)
        elif isinstance(frame, TTSSpeakFrame):
            await self._speak(frame.text)
        else:
            await self.push_frame(frame, direction)


def _session(store):
    with mock.patch.dict(os.environ, {k: v for k, v in os.environ.items() if k not in _NAMES}, clear=True):
        return crowkis.voice_session(client=store)


def _context(question, system=None):
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": question}]
    return LLMContextFrame(context=LLMContext(messages=messages))


def _run(pipeline, *frames):
    down, _ = asyncio.run(run_test(pipeline, frames_to_send=list(frames)))
    return down


@unittest.skipIf(run_test is None, "pipecat-ai not installed")
class WrapperTests(unittest.TestCase):
    def test_a_miss_then_a_hit_spoken_from_the_cache_with_its_audio(self):
        store = SceneStore()
        session = _session(store)
        llm, tts = FakeLLM(), FakeTTS()
        crowkis_llm = CrowkisLLM(llm, session=session)
        down = _run(Pipeline([crowkis_llm, CrowkisTTS(tts)]),
                    _context(QUESTION, "You are Acme's assistant."), SleepFrame(0.2), _context(QUESTION))
        self.assertEqual(len(llm.asked), 1)  # the second time, no LLM
        self.assertEqual(llm.asked[0], [{"role": "system", "content": "You are Acme's assistant."},
                                        {"role": "user", "content": QUESTION}])
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        self.assertEqual(tts.spoke, [ANSWER])  # nor the TTS: the cached clip was played
        replayed = [f for f in down if isinstance(f, TTSAudioRawFrame) and f.audio == PCM]
        self.assertEqual(len(replayed), 2)  # once from the TTS, once from the cache
        (key, _), = store.tool_writes
        self.assertEqual((key["voice"], key["format"]), ("rachel", "pcm16-16000"))

    def test_history_given_to_the_model_counts_as_what_the_caller_said(self):
        # The app's context already holds a turn telling the call something: the later
        # question is answered with the whole context, and nothing is shared.
        store = SceneStore({"What should I pack?": "Light clothes."})
        llm = FakeLLM(reply="For Goa in December, light cotton and a light jacket.")
        history = [{"role": "system", "content": "You are Acme's assistant."},
                   {"role": "user", "content": [{"type": "text", "text": "I'm planning a trip to Goa in December."}]},
                   {"role": "assistant", "content": "Lovely!"},
                   {"role": "user", "content": "What should I pack?"}]
        _run(Pipeline([CrowkisLLM(llm, session=_session(store)), CrowkisTTS(FakeTTS())]),
             LLMContextFrame(context=LLMContext(messages=history)))
        self.assertEqual(len(llm.asked), 1, "not served from the shared cache")
        self.assertEqual(len(llm.asked[0]), 4, "the model read the whole context")
        self.assertEqual((store.writes, store.tool_writes), ([], []))

    def test_plain_history_keeps_the_shared_cache(self):
        store = SceneStore({"What should I pack?": "Light clothes."})
        llm = FakeLLM()
        history = [{"role": "user", "content": "Hi, I have a question."}, {"role": "assistant", "content": "Sure."},
                   {"role": "user", "content": "What should I pack?"}]
        _run(Pipeline([CrowkisLLM(llm, session=_session(store)), CrowkisTTS(FakeTTS())]),
             LLMContextFrame(context=LLMContext(messages=history)))
        self.assertEqual(llm.asked, [], "served from the shared cache")

    def test_a_replayed_clip_has_its_text_for_captions_and_lands_in_the_context_once(self):
        from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair

        store = SceneStore()
        session = _session(store)
        _run(Pipeline([CrowkisLLM(FakeLLM(), session=session), CrowkisTTS(FakeTTS())]), _context(QUESTION))
        writes = len(store.tool_writes)
        self.assertEqual(writes, 1, "the first answer's clip is kept")

        tts = FakeTTS()
        context = LLMContext(messages=[{"role": "user", "content": QUESTION}])
        assistant = LLMContextAggregatorPair(context).assistant()
        seen = []

        class Recorder(FrameProcessor):  # before the aggregator, which consumes the text
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                seen.append(frame)
                await self.push_frame(frame, direction)

        _run(Pipeline([CrowkisLLM(FakeLLM(), session=session), CrowkisTTS(tts), Recorder(), assistant]),
             LLMContextFrame(context=context), SleepFrame(0.3))
        down = seen
        texts = [f for f in down if isinstance(f, TTSTextFrame)]
        self.assertEqual([f.text for f in texts], [ANSWER], "captions and transcripts see the cached answer")
        self.assertTrue(all(getattr(f, "skip_tts", False) for f in texts))
        self.assertTrue(any(isinstance(f, TTSStartedFrame) for f in down) and any(isinstance(f, TTSStoppedFrame) for f in down))
        self.assertEqual(tts.spoke, [], "the TTS never speaks a replayed clip")
        self.assertEqual([m for m in context.get_messages() if m["role"] == "assistant"],
                         [{"role": "assistant", "content": ANSWER}], "the answer is in the context exactly once")
        self.assertEqual(len(store.tool_writes), writes, "a replayed clip is not stored again")

    def test_the_voice_and_sample_rate_come_from_the_tts_service(self):
        store = SceneStore()
        session = _session(store)
        self.assertTrue(session._text_only)
        crowkis_llm = CrowkisLLM(FakeLLM(), session=session)
        tts = FakeTTS(voice="aria")
        tts.sample_rate = 24000
        _run(Pipeline([crowkis_llm, CrowkisTTS(tts)]), _context(QUESTION))
        self.assertEqual((session.voice, session._text_only), ("aria", False))
        self.assertEqual(crowkis_llm.audio.sample_rate, 24000)

    def test_a_session_with_its_own_voice_keeps_it(self):
        store = SceneStore()
        session = crowkis.voice_session(client=store, voice="my-voice")
        _run(Pipeline([CrowkisLLM(FakeLLM(), session=session), CrowkisTTS(FakeTTS(voice="aria"))]), _context(QUESTION))
        self.assertEqual(session.voice, "my-voice")

    def test_the_tts_can_be_told_its_llm(self):
        store = SceneStore()
        crowkis_llm = CrowkisLLM(FakeLLM(), session=_session(store))
        tts = CrowkisTTS(FakeTTS(), llm=crowkis_llm)
        self.assertIs(tts._relay._target, crowkis_llm.audio)
        _run(Pipeline([crowkis_llm, tts]), _context(QUESTION))
        self.assertEqual(len(store.tool_writes), 1)

    def test_the_llm_alone_still_caches_text(self):
        store = SceneStore()
        llm = FakeLLM()
        _run(Pipeline([CrowkisLLM(llm, session=_session(store)), FakeTTS()]),
             _context(QUESTION), SleepFrame(0.2), _context(QUESTION))
        self.assertEqual(len(llm.asked), 1)
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        self.assertEqual(store.tool_writes, [])

    def test_the_llm_services_own_instruction_is_checked_too(self):
        store = SceneStore()
        llm = FakeLLM(reply="Hi Asha! Refunds take five business days.",
                      system_instruction="You are Acme's assistant. The caller is Asha Rao, account 99812.")
        _run(Pipeline([CrowkisLLM(llm, session=_session(store)), CrowkisTTS(FakeTTS())]), _context(QUESTION))
        self.assertEqual(store.writes, [])
        self.assertEqual(store.tool_writes, [])

    def test_the_session_follows_a_change_of_tts_voice(self):
        from pipecat.frames.frames import TTSUpdateSettingsFrame

        store = SceneStore()
        session = _session(store)
        tts = FakeTTS(voice="aria")

        class Switch(FrameProcessor):
            async def process_frame(self, frame, direction):
                await super().process_frame(frame, direction)
                if isinstance(frame, TTSUpdateSettingsFrame):
                    tts._settings.voice = "nova"  # what a real TTS does with the frame
                await self.push_frame(frame, direction)

        crowkis_tts = CrowkisTTS(tts)
        crowkis_tts._processors.insert(1, Switch())  # in front of the relay
        crowkis_tts._link_processors()
        _run(Pipeline([CrowkisLLM(FakeLLM(), session=session), crowkis_tts]),
             TTSUpdateSettingsFrame(settings={}), SleepFrame(0.1), _context(QUESTION))
        self.assertEqual(session.voice, "nova")
        (key, _), = store.tool_writes
        self.assertEqual(key["voice"], "nova")

    def test_the_llm_services_own_calls_work_on_the_wrapper(self):
        llm = FakeLLM()
        llm.register_function = lambda name, handler: ("registered", name)
        wrapped = CrowkisLLM(llm, session=_session(SceneStore()))
        self.assertEqual(wrapped.register_function("weather", None), ("registered", "weather"))
        with self.assertRaises(AttributeError):
            wrapped._not_a_thing

    def test_with_no_tts_after_it_no_clip_is_read_or_kept(self):
        store = SceneStore({QUESTION: ANSWER})
        session = crowkis.voice_session(client=store, voice="my-voice")
        crowkis_llm = CrowkisLLM(FakeLLM(), session=session)
        down = _run(Pipeline([crowkis_llm, FakeTTS()]), _context(QUESTION))
        self.assertEqual(crowkis_llm.audio.sample_rate, 0)
        self.assertFalse([f for f in down if isinstance(f, TTSAudioRawFrame) and f.sample_rate == 0])
        self.assertEqual(store.tool_writes, [])

    def test_a_session_or_session_options_not_both(self):
        with self.assertRaises(ValueError):
            CrowkisLLM(FakeLLM(), session=_session(SceneStore()), serve_above=0.9)

    def test_session_options_make_a_voice_session(self):
        llm = CrowkisLLM(FakeLLM(), client=SceneStore(), serve_above=0.95, agent_id="support")
        self.assertEqual((llm.session.serve_above, llm.session.agent.agent_id), (0.95, "support"))
        self.assertEqual(llm.session.latency_budget_ms, 250)


if __name__ == "__main__":
    unittest.main()
