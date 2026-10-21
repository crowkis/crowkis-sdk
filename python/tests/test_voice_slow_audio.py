"""A hung audio cache never holds a cache hit (K4). With a latency budget the audio step
gets at most twice the budget; past it the hit is served as text (the app's TTS speaks
it) and the audio step finishes in the background. Without a budget, nothing changes."""
import time
import unittest

import crowkis
from crowkis import Agent, VoiceSession

from voice_turns_scenarios import SceneStore

QUESTION = "what is your refund policy"
ANSWER = "Refunds take five business days."
PCM = b"\x01\x02" * 160


class SlowAudio(SceneStore):
    def __init__(self, seconds):
        super().__init__({QUESTION: ANSWER})
        self.seconds = seconds

    def ctoolget(self, *args, **kwargs):
        time.sleep(self.seconds)
        return super().ctoolget(*args, **kwargs)


def _timed_decide(session):
    started = time.perf_counter()
    decision = session.decide(QUESTION)
    return decision, (time.perf_counter() - started) * 1000


class SlowAudioTests(unittest.TestCase):
    def test_a_hung_audio_read_never_holds_a_hit(self):
        session = crowkis.voice_session(client=SlowAudio(1.5), voice="v", synthesise=lambda text: PCM)
        decision, ms = _timed_decide(session)
        self.assertEqual((decision.action, decision.text, decision.audio), ("serve", ANSWER, None))
        self.assertLess(ms, 900, "the hit waited for the hung audio read")
        self.assertEqual(session.audio_unavailable, 1)

    def test_must_still_work_a_quick_audio_read_gives_the_audio(self):
        session = crowkis.voice_session(client=SlowAudio(0), voice="v", synthesise=lambda text: PCM)
        decision, _ = _timed_decide(session)
        self.assertEqual((decision.action, decision.audio), ("serve", PCM))
        self.assertEqual(session.audio_unavailable, 0)

    def test_must_still_work_without_a_budget_the_audio_is_waited_for(self):
        session = VoiceSession(Agent("a", client=SlowAudio(0.6)), voice="v", synthesise=lambda text: PCM)
        decision, ms = _timed_decide(session)
        self.assertEqual(decision.audio, PCM)
        self.assertGreaterEqual(ms, 600)


if __name__ == "__main__":
    unittest.main()
