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


class FakeAgent:
    tenant = "t"

    def __init__(self):
        self._client = FakeClient()


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

    def test_new_answer_is_stored(self):
        self.cache.expect("Yes, we ship to Canada.")
        self.feed(TTSStartedFrame(), TTSAudioRawFrame(b"BBBB", 24000, 1), TTSStoppedFrame())
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_replayed_hit_is_not_glued_onto_the_next_answer(self):
        # A hit replays its stored clip as a bare audio frame: no TTS ran, so no
        # TTSStartedFrame or TTSStoppedFrame comes with it.
        self.feed(TTSAudioRawFrame(b"AAAA", 24000, 1))
        # The next turn is a miss, spoken by the TTS.
        self.cache.expect("Yes, we ship to Canada.")
        self.feed(TTSStartedFrame(), TTSAudioRawFrame(b"BBBB", 24000, 1), TTSStoppedFrame())
        self.assertEqual(self.stored("Yes, we ship to Canada."), b"BBBB")

    def test_every_frame_is_passed_on(self):
        frames = [TTSAudioRawFrame(b"AAAA", 24000, 1), TTSStartedFrame(), TTSStoppedFrame()]
        self.feed(*frames)
        self.assertEqual(self.pushed, frames)


@unittest.skipIf(CrowkisAudioCache is None, "pipecat-ai not installed")
class WriteBackTests(unittest.TestCase):
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
