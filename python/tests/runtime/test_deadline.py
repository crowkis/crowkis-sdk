import concurrent.futures
import threading
import unittest

from crowkis.runtime.deadline import within


class DeadlineTests(unittest.TestCase):
    """V4-3: a lookup that passed its deadline and still waits in the queue never runs."""

    def test_a_queued_late_call_is_cancelled_and_never_runs(self):
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.addCleanup(pool.shutdown)
        release, ran = threading.Event(), []
        pool.submit(release.wait)  # the hung server holds the only worker
        with self.assertRaises(concurrent.futures.TimeoutError):
            within(pool, 20, lambda: ran.append("late"))
        release.set()
        pool.submit(lambda: None).result(timeout=2)  # the queue has drained
        self.assertEqual(ran, [])

    def test_work_in_time_returns_and_its_error_is_raised_as_it_is(self):
        pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.addCleanup(pool.shutdown)
        self.assertEqual(within(pool, 1000, lambda x: x + 1, 1), 2)
        with self.assertRaises(ZeroDivisionError):
            within(pool, 1000, lambda: 1 / 0)


if __name__ == "__main__":
    unittest.main()
