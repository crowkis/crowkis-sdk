"""Self-contained SDK tests: RESP protocol, agent memory, LangChain cache, help.

No server, no network, no real LangChain — LangChain is stubbed so the cache
mapping logic is verified in isolation. Run:  python -m unittest discover -s tests
"""

import json
import sys
import types
import unittest
from io import BytesIO

# ── stub langchain_core BEFORE importing the integration ────────────────────
_caches = types.ModuleType("langchain_core.caches")
_outputs = types.ModuleType("langchain_core.outputs")
_load = types.ModuleType("langchain_core.load")


class _BaseCache:  # minimal stand-in for langchain_core.caches.BaseCache
    pass


class _Generation:
    def __init__(self, text=""):
        self.text = text

    def __eq__(self, other):
        return getattr(other, "text", None) == self.text


_caches.BaseCache = _BaseCache
_caches.RETURN_VAL_TYPE = list
_outputs.Generation = _Generation
_load.dumps = lambda obj: json.dumps([g.text for g in obj])
_load.loads = lambda s: [_Generation(text=t) for t in json.loads(s)]

sys.modules.setdefault("langchain_core", types.ModuleType("langchain_core"))
sys.modules["langchain_core.caches"] = _caches
sys.modules["langchain_core.outputs"] = _outputs
sys.modules["langchain_core.load"] = _load

from crowkis import CrowkisMemory, help_text  # noqa: E402
from crowkis.client import CrowkisError, _encode, _read_resp  # noqa: E402
from crowkis.integrations.langchain import CrowkisCache  # noqa: E402


class ProtocolTests(unittest.TestCase):
    def test_encode_matches_resp(self):
        self.assertEqual(_encode(["PING"]), b"*1\r\n$4\r\nPING\r\n")
        self.assertEqual(
            _encode(["SET", "k", "v"]),
            b"*3\r\n$3\r\nSET\r\n$1\r\nk\r\n$1\r\nv\r\n",
        )

    def test_read_resp_types(self):
        self.assertEqual(_read_resp(BytesIO(b"+PONG\r\n")), "PONG")
        self.assertEqual(_read_resp(BytesIO(b":42\r\n")), 42)
        self.assertEqual(_read_resp(BytesIO(b"$5\r\nhello\r\n")), b"hello")
        self.assertIsNone(_read_resp(BytesIO(b"$-1\r\n")))
        self.assertEqual(_read_resp(BytesIO(b"*2\r\n:1\r\n:2\r\n")), [1, 2])

    def test_read_resp_error_raises(self):
        with self.assertRaises(CrowkisError):
            _read_resp(BytesIO(b"-ERR boom\r\n"))


class MemMock:
    def __init__(self):
        self.calls = []

    def cmemset(self, agent, fact, user=None, ex=None):
        self.calls.append(("set", agent, fact, user, ex))
        return "OK"

    def cmemget(self, agent, query, user=None, k=None):
        self.calls.append(("get", agent, query, user, k))
        return ["fact"]

    def close(self):
        self.calls.append(("close",))


class MemoryTests(unittest.TestCase):
    def test_remember_and_recall_pass_agent_and_user(self):
        mock = MemMock()
        mem = CrowkisMemory("bot", client=mock, user="alice")
        mem.remember("Alice likes email", ttl=60)
        mem.recall("contact preference", k=3)
        self.assertEqual(mock.calls[0], ("set", "bot", "Alice likes email", "alice", 60))
        self.assertEqual(mock.calls[1], ("get", "bot", "contact preference", "alice", 3))

    def test_empty_agent_rejected(self):
        with self.assertRaises(ValueError):
            CrowkisMemory("", client=MemMock())

    def test_does_not_close_borrowed_client(self):
        mock = MemMock()
        CrowkisMemory("bot", client=mock).close()
        self.assertNotIn(("close",), mock.calls)


class CacheMock:
    def __init__(self):
        self.store = {}
        self.calls = []

    def cget_hit(self, query, model=None, threshold=None):
        self.calls.append(("cget_hit", query, model, threshold))
        val = self.store.get(query)
        return None if val is None else types.SimpleNamespace(text=val)

    def cset(self, query, response, ttl=None, model=None):
        self.calls.append(("cset", query, response, ttl, model))
        self.store[query] = response if isinstance(response, str) else response.decode()

    def cflush(self):
        self.calls.append(("cflush",))
        self.store.clear()
        return 0


class LangChainCacheTests(unittest.TestCase):
    def test_miss_then_roundtrip(self):
        mock = CacheMock()
        cache = CrowkisCache(client=mock, ttl=120)
        self.assertIsNone(cache.lookup("what is 2+2", "gpt"))
        cache.update("what is 2+2", "gpt", [_Generation(text="four")])
        got = cache.lookup("what is 2+2", "gpt")
        self.assertEqual(got, [_Generation(text="four")])

    def test_update_tags_model_and_ttl(self):
        mock = CacheMock()
        CrowkisCache(client=mock, ttl=99).update("q", "llm-abc", [_Generation(text="a")])
        kind, query, payload, ttl, model = mock.calls[-1]
        self.assertEqual((kind, query, ttl, model), ("cset", "q", 99, "llm-abc"))
        self.assertEqual(json.loads(payload), ["a"])

    def test_clear_flushes(self):
        mock = CacheMock()
        CrowkisCache(client=mock).clear()
        self.assertIn(("cflush",), mock.calls)


class HelpTests(unittest.TestCase):
    def test_help_lists_core_groups(self):
        text = help_text()
        for needle in ["Semantic cache", "Agent memory", "Framework integrations", "crowkis.com"]:
            self.assertIn(needle, text)

    def test_help_topic_filters(self):
        text = help_text("memory")
        self.assertIn("Agent memory", text)
        self.assertNotIn("Cost & FinOps", text)

    def test_help_unknown_topic_is_graceful(self):
        self.assertIn("no help topic matched", help_text("nonsense-xyz"))


class HighLevelApiTests(unittest.TestCase):
    """The model-agnostic cache API — works with any model, no vendor coupling."""

    def _client(self):
        from crowkis import Crowkis

        c = Crowkis(tenant="t")
        store: dict = {}
        c.cget = lambda p, **k: store.get(p)  # type: ignore[assignment]
        c.cset = lambda p, a, **k: store.__setitem__(  # type: ignore[assignment]
            p, a if isinstance(a, bytes) else str(a).encode()
        )
        return c

    def test_cached_decorator_invokes_model_once(self):
        c = self._client()
        calls = []

        @c.cached(ttl=60)
        def answer(prompt: str) -> str:  # could call ANY model
            calls.append(prompt)
            return f"A::{prompt}"

        self.assertEqual(answer("how do refunds work?"), "A::how do refunds work?")
        self.assertEqual(answer("how do refunds work?"), "A::how do refunds work?")
        self.assertEqual(len(calls), 1, "model must be invoked only on the miss")

    def test_ask_computes_then_recalls(self):
        c = self._client()
        calls = []

        def compute(p):
            calls.append(p)
            return "X"

        self.assertEqual(c.ask("brand new q", compute), "X")
        self.assertEqual(c.ask("brand new q", compute), "X")
        self.assertEqual(len(calls), 1)

    def test_short_client_alias_exists(self):
        import crowkis

        self.assertIs(crowkis.Crowkis, crowkis.CrowkisClient)
        self.assertIs(crowkis.AsyncCrowkis, crowkis.AsyncCrowkisClient)


if __name__ == "__main__":
    unittest.main()
