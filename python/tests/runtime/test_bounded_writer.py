"""v4 P2: BoundedWriter alone (a quick write, a slow one, a full queue of slow ones)."""
import logging
import threading
import unittest

from crowkis.runtime import BoundedWriter, WriteWorkers

DEADLINE_S = 0.05


class BoundedWriterTests(unittest.TestCase):
    def setUp(self):
        self.workers = WriteWorkers(2, name="test-write")
        self.counts = []
        self.release = threading.Event()

    def writer(self, cap=10):
        return BoundedWriter(self.workers, lambda: cap, self.counts.append, logging.getLogger("test"))

    def test_a_quick_write_is_done(self):
        self.assertIsNone(self.writer().write(lambda: None, deadline_s=DEADLINE_S))
        self.assertEqual(self.counts, [])

    def test_a_slow_write_is_not_confirmed_and_finishes_later(self):
        verdict = self.writer().write(self.release.wait, deadline_s=DEADLINE_S)
        self.assertEqual((verdict.rule, verdict.outcome), ("BoundedWrite", "slow_write"))
        self.assertIn("not confirmed", verdict.reason)
        self.assertEqual(self.counts, ["slow_writes"])
        self.release.set()
        self.workers.wait()
        self.assertEqual(self.workers.pending, set())

    def test_past_the_cap_a_new_answer_is_not_written(self):
        writer = self.writer(cap=1)
        writer.write(self.release.wait, deadline_s=DEADLINE_S)
        verdict = writer.write(lambda: None, deadline_s=DEADLINE_S)
        self.assertIn("not written", verdict.reason)
        self.release.set()
        self.workers.wait()

    def test_an_error_before_the_deadline_is_raised(self):
        def refuse():
            raise ConnectionError("refused")
        with self.assertRaises(ConnectionError):
            self.writer().write(refuse, deadline_s=1.0)


if __name__ == "__main__":
    unittest.main()
