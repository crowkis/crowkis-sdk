"""A slow server must not stall a turn after a miss (Phase 3: "a slow server means a miss
within the budget, not a stall"). With a latency budget (voice_session(): 250 ms) the
turn waits for the new answer's write no longer than the budget; the write finishes in
the background. An audio clip is stored in the background. Without a budget
(VoiceSession(...) as before) the write is waited for, as it always was. Agent.speak()
still stores the clip it makes before it returns (a public function: unchanged)."""
import asyncio
import time
import unittest
import unittest.mock

import crowkis
from crowkis import Agent, VoiceSession
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice import _wait_for_writes
from crowkis.voice_turns import AudioClips

from voice_turns_scenarios import SceneStore


class ConformanceStore(SceneStore):
    """A server that answers at once (SceneStore), with no Voice add-on."""


class Clips(AudioClips):
    def __init__(self, session, sample_rate):
        self._init_clips(session, sample_rate)

QUESTION = "what is your refund policy"
ANSWER = "Refunds take five business days."


class SlowWrites(ConformanceStore):
    """Lookups answer at once; every write hangs for a while."""

    def __init__(self, seconds=1.0):
        super().__init__()
        self.seconds = seconds

    def cset(self, *args, **kwargs):
        time.sleep(self.seconds)
        super().cset(*args, **kwargs)

    def ctoolset(self, *args, **kwargs):
        time.sleep(self.seconds)
        super().ctoolset(*args, **kwargs)


def _timed(fn):
    started = time.perf_counter()
    result = fn()
    return result, (time.perf_counter() - started) * 1000


class SlowWriteTests(unittest.TestCase):
    def setUp(self):
        _wait_for_writes()  # no other test's slow writes still queued
        _wait_for_audio_stores()

    def test_with_a_budget_a_slow_write_never_holds_the_turn(self):
        store = SlowWrites()
        session = crowkis.voice_session(client=store)
        decision, ms = _timed(lambda: session.answer(QUESTION, lambda m: ANSWER))
        self.assertTrue(decision.needs_model)
        self.assertLess(ms, 600, "the turn waited for the slow write")
        self.assertFalse(decision.stored, "not confirmed, so not reported as saved")
        self.assertIn("latency budget", decision.not_stored)
        self.assertEqual(session.slow_writes, 1)
        self.assertEqual(session.stats()["slow_writes"], 1)
        time.sleep(1.2)  # the write still lands, in the background
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])

    def test_streaming_and_record_are_bounded_too(self):
        for name, run in (
            ("respond", lambda s: "".join(s.respond(QUESTION, lambda m: iter([ANSWER])))),
            ("record", lambda s: s.record(s.decide(QUESTION), ANSWER)),
        ):
            with self.subTest(name):
                session = crowkis.voice_session(client=SlowWrites())
                _, ms = _timed(lambda: run(session))
                self.assertLess(ms, 600)

    def test_a_late_write_that_fails_is_counted(self):
        class Failing(SlowWrites):
            def cset(self, *args, **kwargs):
                time.sleep(0.5)
                raise RuntimeError("refused")

        session = crowkis.voice_session(client=Failing())
        session.answer(QUESTION, lambda m: ANSWER)
        time.sleep(0.8)
        self.assertEqual((session.slow_writes, session.learn_errors), (1, 1))

    def test_a_hung_server_never_queues_writes_without_limit(self):
        from crowkis import voice

        class Hung(ConformanceStore):
            def cset(self, *args, **kwargs):
                release.wait(5)

        import threading
        release = threading.Event()
        session = crowkis.voice_session(client=Hung())
        try:
            with unittest.mock.patch.object(voice, "_WRITES_MAX", 3):
                questions = ["what is your refund policy", "how do I reset my password", "what are your opening hours",
                             "do you ship to canada", "how do I cancel my plan"]
                outcomes = [session.answer(q, lambda m: ANSWER).not_stored for q in questions]
                self.assertLessEqual(len(voice._PENDING_WRITES), 3)
        finally:
            release.set()
        self.assertEqual(session.slow_writes, 5)
        self.assertTrue(all("latency budget" in o for o in outcomes), outcomes)

    def test_a_write_within_the_budget_is_reported_as_before(self):
        class Refusing(ConformanceStore):
            def cset(self, *args, **kwargs):
                raise RuntimeError("security pipeline refused it")

        session = crowkis.voice_session(client=Refusing())
        decision = session.answer(QUESTION, lambda m: ANSWER)
        self.assertIn("refused", decision.not_stored)
        self.assertEqual((session.slow_writes, session.learn_errors), (0, 1))

    def test_must_still_work_without_a_budget_the_write_is_waited_for(self):
        store = SlowWrites(0.4)
        session = VoiceSession(Agent("caller", client=store), voice="v")
        _, ms = _timed(lambda: session.answer(QUESTION, lambda m: ANSWER))
        self.assertGreaterEqual(ms, 400)
        self.assertEqual(store.writes, [[QUESTION, ANSWER, False]])
        self.assertEqual(session.slow_writes, 0)

    def test_an_audio_clip_is_stored_in_the_background(self):
        store = SlowWrites()
        session = crowkis.voice_session(client=store, voice="v")
        clips = Clips(session, 16000)

        async def run():
            started = time.perf_counter()
            await clips._store(ANSWER, b"\x01\x02" * 160)
            return (time.perf_counter() - started) * 1000

        self.assertLess(asyncio.run(run()), 300)
        _wait_for_audio_stores()
        self.assertEqual(len(store.tool_writes), 1)

    def test_a_clip_store_that_fails_in_the_background_is_counted(self):
        class Failing(ConformanceStore):
            def ctoolset(self, *args, **kwargs):
                raise RuntimeError("audio cache down")

        session = crowkis.voice_session(client=Failing(), voice="v")
        asyncio.run(Clips(session, 16000)._store(ANSWER, b"" * 160))
        _wait_for_audio_stores()
        self.assertEqual(session.agent.audio_errors, 1)


if __name__ == "__main__":
    unittest.main()
