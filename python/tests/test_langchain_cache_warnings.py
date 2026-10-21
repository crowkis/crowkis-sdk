"""The LangChain cache restores a hit with langchain_core's loads(allowed_objects="core"):
no pending-deprecation warning on every hit, and only LangChain's own classes are rebuilt
from cached data. Skipped without langchain-core."""
import unittest
import warnings

try:
    from langchain_core.outputs import Generation

    from crowkis.integrations.langchain import CrowkisCache
except ImportError:  # pragma: no cover
    CrowkisCache = None

from crowkis import CacheHit


class _Store:
    tenant = None

    def __init__(self):
        self.data = {}

    def cset(self, query, response, **kwargs):
        self.data[query] = response

    def cget_hit(self, query, **kwargs):
        value = self.data.get(query)
        return value and CacheHit(response=value.encode(), similarity=1.0, ttl_remaining=60,
                                  matched_key=b"k", confidence=1.0, hit_type="exact")


@unittest.skipIf(CrowkisCache is None, "langchain-core not installed")
class LangChainCacheWarningTests(unittest.TestCase):
    def test_a_hit_round_trips_without_a_warning_each_time(self):
        cache = CrowkisCache(client=_Store())
        cache.update("p", "llm", [Generation(text="hi")])
        cache.lookup("p", "llm")  # LangChain's one-time beta notice, if any, comes here
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            hit = cache.lookup("p", "llm")
        self.assertEqual(hit[0].text, "hi")
        self.assertEqual([w for w in caught if "allowed_objects" in str(w.message)], [])

    def test_must_still_work_plain_text_from_another_writer_is_a_generation(self):
        store = _Store()
        store.data["p"] = "plain answer"
        self.assertEqual(CrowkisCache(client=store).lookup("p", "llm")[0].text, "plain answer")


if __name__ == "__main__":
    unittest.main()
