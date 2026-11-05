"""v4 P3: CacheLookup refuses a late hit."""
import concurrent.futures
import time
import unittest

from crowkis.runtime import CacheLookup

POOL = concurrent.futures.ThreadPoolExecutor(max_workers=2)
HIT = {"route": "cache", "answer": "Nine to five.", "confidence": 0.99}


class CacheLookupTests(unittest.TestCase):
    def test_a_hit_that_came_back_after_the_budget(self):
        started = time.monotonic() - 1.0  # the budget was spent before the hit came back
        hit, verdict = CacheLookup(POOL).find(lambda: HIT, started, 100)
        self.assertEqual((hit, verdict.rule), (HIT, "LookupDeadline"))

    def test_an_unreachable_cache_means_the_model_answers(self):
        def down():
            raise ConnectionError("down")
        self.assertEqual(CacheLookup(POOL).find(down, time.monotonic(), None)[1].rule, "CacheUnavailable")


if __name__ == "__main__":
    unittest.main()
