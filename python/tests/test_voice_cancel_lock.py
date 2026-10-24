"""cancel() (a barge-in) takes the turn lock, like decide() and recording do: a save
finishing on another thread can never add to the transcript in the middle of cancel()
trimming it. Python only: Node runs one thing at a time."""
import threading
import time
import unittest

from crowkis import Agent, VoiceSession

from voice_turns_scenarios import SceneStore


class CancelLockTests(unittest.TestCase):
    def test_cancel_waits_for_the_turn_lock(self):
        session = VoiceSession(Agent("a", client=SceneStore()), voice="v")
        session.decide("what is your refund policy")
        done = threading.Event()
        with session._turn_lock:
            worker = threading.Thread(target=lambda: (session.cancel(), done.set()))
            worker.start()
            time.sleep(0.1)
            self.assertFalse(done.is_set(), "cancel() ran while another thread held the turn lock")
        worker.join(2)
        self.assertTrue(done.is_set())
        self.assertEqual(session.barge_ins, 1)

    def test_must_still_work_cancel_from_the_same_thread_inside_the_lock(self):
        session = VoiceSession(Agent("a", client=SceneStore()), voice="v")
        session.decide("what is your refund policy")
        with session._turn_lock:  # re-entrant: a caller already holding it is not blocked
            self.assertTrue(session.cancel())


if __name__ == "__main__":
    unittest.main()
