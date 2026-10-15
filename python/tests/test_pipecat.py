"""Server-free tests for crowkis.integrations.pipecat.

Skipped when pipecat-ai is not installed. Frames are fed straight into the
processors; push_frame is replaced so nothing needs a running pipeline. Run:
python -m pytest tests/ -q
"""

import asyncio
import base64
import json
import unittest

try:
    from pipecat.frames.frames import (
        LLMFullResponseEndFrame,
        LLMFullResponseStartFrame,
        LLMTextFrame,
        TTSAudioRawFrame,
        TTSStartedFrame,
        TTSStoppedFrame,
    )

    from crowkis.integrations.pipecat import TTS_TOOL, CrowkisAudioCache, CrowkisWriteBack
except ImportError:  # pipecat-ai is an optional extra
    CrowkisAudioCache = None


class FakeClient:
    def __init__(self):
        self.stored = {}

    def ctoolset(self, tool, args_str, value, *, ex=None, tenant=None):
        self.stored[(tool, args_str)] = value

    def ctoolget(self, tool, args_str, *, tenant=None):
        return self.stored.get((tool, args_str))


class FakeAgent:
    tenant = "t"

    def __init__(self, holds=False):
        self._client = FakeClient()
        self._holds = holds

    def decides(self):
        return self._holds


class FakeSession:
    voice = "test-voice"
    ttl = 60

    def __init__(self):
        self.agent = FakeAgent()


def _key(text):
    return json.dumps({"voice": FakeSession.voice, "text": text}, sort_keys=True)


@unittest.skipIf(CrowkisAudioCache is None, "pipecat-ai not installed")
class AudioCacheTests(unittest.TestCase):
    def setUp(self):
        self.session = FakeSession()
        self.cache = CrowkisAudioCache(self.session, sample_rate=24000)
        self.pushed = []

        async def push_frame(frame, direction=None):
            self.pushed.append(frame)

        self.cache.push_frame = push_frame

    def feed(self, *frames):
        async def run():
            for frame in frames:
                await self.cache.process_frame(frame, None)

        asyncio.run(run())

    def stored(self, text):
        clip = self.session.agent._client.stored.get((TTS_TOOL, _key(text)))
        return base64.b64decode(clip) if clip else None

    def settle(self, text, shareable):
        asyncio.run(self.cache.settle(text, shareable))

    def speak(self, audio=b"BBBB"):
        self.feed(TTSStartedFrame(), TTSAudioRawFrame(audio, 24000, 1), TTSStoppedFrame())

    def test_a_damaged_clip_is_a_miss_never_noise(self):
        stored = self.session.agent._client.stored
        stored[(TTS_TOOL, _key("ok"))] = base64.b64encode(b"\x00\x01audio").decode()
        self.assertEqual(asyncio.run(self.cache.get("ok")), b"\x00\x01audio")
        # A lenient decoder skips the "_" and plays what is left.
        stored[(TTS_TOOL, _key("damaged"))] = "QUJD/pii_card_k12ab/QUJD"
        self.assertIsNone(asyncio.run(self.cache.get("damaged")))
        self.assertIsNone(asyncio.run(self.cache.get("never stored")))

    def test_a_served_answer_is_stored(self):
        self.cache.expect("Yes, we ship to Canada.", shareable=True)
        self.speak()
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_a_new_answer_waits_for_its_ruling(self):
        self.cache.expect("Yes, we ship to Canada.")
        self.speak()
        self.assertIsNone(self.stored("Yes, we ship to Canada."))
        self.settle("Yes, we ship to Canada.", True)
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_a_ruling_that_comes_first_waits_for_its_clip(self):
        self.cache.expect("Yes, we ship to Canada.")
        self.settle("Yes, we ship to Canada.", True)
        self.speak()
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_an_answer_that_is_not_shared_keeps_no_clip(self):
        answer = "Yes, order 48213 for Priya Shah left this morning."
        self.cache.expect(answer)
        self.speak()
        self.settle(answer, False)
        self.cache.expect(answer)
        self.settle(answer, False)
        self.speak()
        self.assertEqual(self.session.agent._client.stored, {})

    def test_replayed_hit_is_not_glued_onto_the_next_answer(self):
        # A hit replays its stored clip as a bare audio frame: no TTS ran, so no
        # TTSStartedFrame or TTSStoppedFrame comes with it.
        self.feed(TTSAudioRawFrame(b"AAAA", 24000, 1))
        # The next turn is a miss, spoken by the TTS.
        self.cache.expect("Yes, we ship to Canada.")
        self.feed(TTSStartedFrame(), TTSAudioRawFrame(b"BBBB", 24000, 1), TTSStoppedFrame())
        self.settle("Yes, we ship to Canada.", True)
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_every_frame_is_passed_on(self):
        frames = [TTSAudioRawFrame(b"AAAA", 24000, 1), TTSStartedFrame(), TTSStoppedFrame()]
        self.feed(*frames)
        self.assertEqual(self.pushed, frames)


def _answer_frames(*parts):
    return [LLMFullResponseStartFrame(), *(LLMTextFrame(p) for p in parts), LLMFullResponseEndFrame()]


@unittest.skipIf(CrowkisAudioCache is None, "pipecat-ai not installed")
class WriteBackTests(unittest.TestCase):
    def speak_new_answer(self, saved, *, holds=False):
        """The model answers, the write-back rules on it, and the TTS speaks it.
        Returns the clips the cache kept."""

        class Session(FakeSession):
            def __init__(self):
                self.agent = FakeAgent(holds=holds)

            def _record_model_turn(self, question, answer):
                return saved

        class Gate:
            question = "has my order shipped"
            messages = []

        session = Session()
        audio = CrowkisAudioCache(session, sample_rate=24000)
        writeback = CrowkisWriteBack(session, Gate(), audio)

        async def push_frame(frame, direction=None):
            pass

        writeback.push_frame = audio.push_frame = push_frame

        async def run():
            for frame in _answer_frames("It left ", "this morning."):
                await writeback.process_frame(frame, None)
            for frame in (TTSStartedFrame(), TTSAudioRawFrame(b"CCCC", 24000, 1), TTSStoppedFrame()):
                await audio.process_frame(frame, None)

        asyncio.run(run())
        return session.agent._client.stored

    def test_the_clip_of_a_saved_answer_is_kept(self):
        self.assertEqual(len(self.speak_new_answer("saved")), 1)

    def test_no_clip_for_an_answer_that_is_not_shared_word_for_word(self):
        for saved in ("private", "kept", "template", "refused", "interrupted", "not_saved", "non_answer"):
            self.assertEqual(self.speak_new_answer(saved), {}, saved)

    def test_no_clip_while_the_decision_engine_holds_answers(self):
        # Not shared until the engine vouches for it; the clip is made when it is served.
        self.assertEqual(self.speak_new_answer("saved", holds=True), {})

    def test_the_report_says_what_happened_to_the_answer(self):
        recorded, reports = [], []

        class Session(FakeSession):
            def _record_model_turn(self, question, answer):
                recorded.append((question, answer))
                return "saved"

        class Gate:
            question = "what is the refund policy"
            messages = [{"role": "user", "content": "what is the refund policy"}]

        async def on_answer(info):
            reports.append(info)

        session = Session()
        audio = CrowkisAudioCache(session, sample_rate=24000)
        writeback = CrowkisWriteBack(session, Gate(), audio, on_answer=on_answer)

        async def push_frame(frame, direction=None):
            pass

        writeback.push_frame = push_frame

        async def run():
            for frame in (LLMFullResponseStartFrame(), LLMTextFrame("We refund "), LLMTextFrame("in 3 days."),
                          LLMFullResponseEndFrame()):
                await writeback.process_frame(frame, None)

        asyncio.run(run())
        self.assertEqual(recorded, [("what is the refund policy", "We refund in 3 days.")])
        self.assertEqual(reports[0]["saved"], "saved")
        self.assertEqual(reports[0]["answer"], "We refund in 3 days.")


if __name__ == "__main__":
    unittest.main()
