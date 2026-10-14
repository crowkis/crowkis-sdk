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


def _scripted(replies, **kwargs):
    """A client whose execute records each frame and answers with the next reply
    (an exception instance is raised, as an error reply is)."""
    from crowkis import CrowkisClient

    client = CrowkisClient(**kwargs)
    sent = []
    queue = list(replies)

    def execute(*args):
        sent.append([a.decode() if isinstance(a, bytes) else a for a in args])
        reply = queue.pop(0)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    client.execute = execute  # type: ignore[assignment]
    return client, sent


class NodeParityControlTests(unittest.TestCase):
    """The behaviour the Node client was fixed to match (B1-B3) still holds here."""

    def test_cmemforget_with_tenant_and_no_query_sends_empty_query(self):
        client, sent = _scripted([3], tenant="acme")
        self.assertEqual(client.cmemforget("bot"), 3)
        self.assertEqual(sent, [["CMEMFORGET", "bot", "", "TENANT", "acme"]])

    def test_busy_retry_seconds(self):
        from crowkis.client import _busy_retry_seconds

        self.assertEqual(_busy_retry_seconds(CrowkisError("BUSY queue full; retry-after-ms 60")), 0.06)
        self.assertEqual(_busy_retry_seconds(CrowkisError("BUSY try later")), 0.05)
        self.assertEqual(_busy_retry_seconds(CrowkisError("BUSY retry-after-ms=999999")), 2.0)
        self.assertIsNone(_busy_retry_seconds(CrowkisError("ERR boom")))

    def test_unknown_reply_type_is_a_client_error(self):
        with self.assertRaisesRegex(CrowkisError, "unexpected RESP frame"):
            _read_resp(BytesIO(b"?what\r\n"))


class NewOperatorCommandTests(unittest.TestCase):
    """CBUDGET RESET, STATS, SWEEP: exact frames and reply shaping."""

    def test_frames_and_replies(self):
        budget = {"tenant": "acme", "status": "ok", "used_pct": 0.0}
        engine = {"memtable_bytes": 10, "memtable_keys": 2, "l0": 1}
        client, sent = _scripted([budget, budget, budget, engine, None, 7, None], tenant="acme")
        self.assertEqual(client.cbudget_reset(), budget)
        client.cbudget_reset("other")
        client.tenant = None
        self.assertEqual(client.cbudget_reset(), budget)
        self.assertEqual(client.stats(), engine)
        self.assertEqual(client.stats(), {})
        self.assertEqual(client.sweep(), 7)
        self.assertEqual(client.sweep(), 0)
        self.assertEqual(sent, [
            ["CBUDGET", "RESET", "acme"],
            ["CBUDGET", "RESET", "other"],
            ["CBUDGET", "RESET", "default"],
            ["STATS"], ["STATS"], ["SWEEP"], ["SWEEP"],
        ])

    def test_null_and_error_replies(self):
        client, _ = _scripted([None, CrowkisError("ERR CBUDGET RESET requires tenant"), [1]])
        self.assertEqual(client.cbudget_reset("acme"), {})
        with self.assertRaisesRegex(CrowkisError, "requires tenant"):
            client.cbudget_reset("acme")
        self.assertEqual(client.stats(), {})


class NewPromptCommandTests(unittest.TestCase):
    """CPROMPT DEL / ROLLBACK / RENDER / AB / ABSET: exact frames and reply shaping."""

    def test_frames_minimal_and_every_option(self):
        client, sent = _scripted([
            1, 0, 3, 4, b"hi Ana", None, b"x",
            [2, b"v2 text"], None, [1, b"v1"], "OK", "OK", "OK",
        ], tenant="client-wide")
        self.assertIs(client.cprompt_del("greet"), True)
        self.assertIs(client.cprompt_del("greet", tenant="acme"), False)
        self.assertEqual(client.cprompt_rollback("greet", 1), 3)
        self.assertEqual(client.cprompt_rollback("greet", 2, tenant="acme"), 4)
        self.assertEqual(client.cprompt_render("greet"), b"hi Ana")
        self.assertIsNone(client.cprompt_render(
            "greet", version=2, tenant="acme", vars={"name": "Ana", "n": 1, "q": "a=b c", "नाम": "अना"}))
        client.cprompt_render("greet", version=0, vars={})
        self.assertEqual(client.cprompt_ab("greet"), (2, b"v2 text"))
        self.assertIsNone(client.cprompt_ab("greet", subject="user-9", tenant="acme"))
        client.cprompt_ab("greet", subject="TENANT")
        self.assertIs(client.cprompt_abset("greet", {1: 70, 2: 30}), True)
        self.assertIs(client.cprompt_abset("greet", {1: 100}, tenant="acme"), True)
        self.assertIs(client.cprompt_abset("greet"), True)
        self.assertEqual(sent, [
            ["CPROMPT", "DEL", "greet"],
            ["CPROMPT", "DEL", "greet", "TENANT", "acme"],
            ["CPROMPT", "ROLLBACK", "greet", "1"],
            ["CPROMPT", "ROLLBACK", "greet", "2", "TENANT", "acme"],
            ["CPROMPT", "RENDER", "greet"],
            ["CPROMPT", "RENDER", "greet", "2", "TENANT", "acme", "VARS", "name=Ana", "n=1", "q=a=b c", "नाम=अना"],
            ["CPROMPT", "RENDER", "greet", "0"],
            ["CPROMPT", "AB", "greet"],
            ["CPROMPT", "AB", "greet", "TENANT", "acme", "SUBJECT", "user-9"],
            ["CPROMPT", "AB", "greet", "SUBJECT", "TENANT"],
            ["CPROMPT", "ABSET", "greet", "1", "70", "2", "30"],
            ["CPROMPT", "ABSET", "greet", "1", "100", "TENANT", "acme"],
            ["CPROMPT", "ABSET", "greet"],
        ])

    def test_null_error_and_misreadable_arguments(self):
        client, sent = _scripted([
            None, None,
            CrowkisError("ERR no such prompt 'nope'"),
            CrowkisError("ERR no version 9 for 'greet'"),
            CrowkisError("ERR A/B weights must be > 0"),
            CrowkisError("ERR CPROMPT: unexpected reply"),
        ])
        self.assertIs(client.cprompt_del("nope"), False)
        self.assertEqual(client.cprompt_rollback("nope", 1), 0)
        with self.assertRaisesRegex(CrowkisError, "no such prompt"):
            client.cprompt_render("nope")
        with self.assertRaisesRegex(CrowkisError, "no version 9"):
            client.cprompt_rollback("greet", 9)
        with self.assertRaisesRegex(CrowkisError, "must be > 0"):
            client.cprompt_abset("greet", {1: 0})
        with self.assertRaisesRegex(CrowkisError, "unexpected reply"):
            client.cprompt_ab("greet")
        for bad in ({"a=b": 1}, {"": 1}):
            with self.assertRaisesRegex(ValueError, 'no "="'):
                client.cprompt_render("greet", vars=bad)
        for bad in ({1: 0.5}, {"v1": 50}, {1: -5}, {1: True}):
            with self.assertRaisesRegex(ValueError, "whole numbers"):
                client.cprompt_abset("greet", bad)
        self.assertEqual(len(sent), 6, "a rejected argument must not reach the server")

    def test_a_numeric_subject_is_sent_as_its_digits_and_weights_stay_in_range(self):
        client, sent = _scripted([None, None, "OK"])
        client.cprompt_ab("greet", subject=5)
        client.cprompt_ab("greet", subject=123456789)
        # The largest weight the server keeps (u32); one above it is refused here.
        self.assertIs(client.cprompt_abset("greet", {1: 4294967295}), True)
        with self.assertRaisesRegex(ValueError, "whole numbers"):
            client.cprompt_abset("greet", {1: 10, 2: 5_000_000_000})
        self.assertEqual(sent, [
            ["CPROMPT", "AB", "greet", "SUBJECT", "5"],
            ["CPROMPT", "AB", "greet", "SUBJECT", "123456789"],
            ["CPROMPT", "ABSET", "greet", "1", "4294967295"],
        ])

    def test_help_lists_the_new_operator_commands(self):
        self.assertIn("cbudget_reset", help_text("cost"))
        self.assertIn("client.stats() / client.sweep()", help_text("operations"))


if __name__ == "__main__":
    unittest.main()
