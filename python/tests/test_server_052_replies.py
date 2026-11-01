"""Server replies changed in Crowkis 0.5.2: CSET NOTSTORED, CSCAN per tenant,
CMEMEXTRACT limits, AUTH with no server token, EX 0 refused."""

import asyncio
import logging
import socket
import threading
import unittest

from crowkis import CrowkisMemory
from crowkis.client import AsyncCrowkisClient, CrowkisClient, CrowkisError

SECRET = "tok-9c1e-very-secret"
NO_PASSWORD = (
    "-ERR AUTH <password> called without any password configured for the default user. "
    "Are you sure your configuration is correct?\r\n"
)
PII_REASON = (
    "the answer holds personal details the question does not name, so it would never be "
    "served; send it with TEMPLATE and {slot} placeholders for those details to cache its shape"
)


def _bulk(value):
    data = value if isinstance(value, bytes) else str(value).encode()
    return b"$%d\r\n%s\r\n" % (len(data), data)


def _facts(text):
    """At most one fact per clause, as the server's extractor: split on the
    same ends, and here every clause long enough counts (the worst case)."""
    out, seen = [], set()
    for clause in text.replace("!", ".").replace("?", ".").replace("\n", ".").split("."):
        clause = clause.strip()
        if len(clause) >= 8 and len(clause.split()) >= 3 and clause.lower() not in seen:
            seen.add(clause.lower())
            out.append(clause)
    return out


class FakeServer:
    """A local RESP server that answers like Crowkis 0.5.2 and records every command."""

    def __init__(self, cset_reply="+OK\r\n", auth_reply="+OK\r\n"):
        self.cset_reply = cset_reply
        self.auth_reply = auth_reply
        self.commands = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def close(self):
        self.listener.close()

    def _accept(self):
        while True:
            try:
                conn, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self._serve, args=(conn,), daemon=True).start()

    def _serve(self, conn):
        reader = conn.makefile("rb")
        with conn:
            while True:
                head = reader.readline()
                if not head:
                    return
                args = []
                for _ in range(int(head[1:])):
                    size = int(reader.readline()[1:])
                    args.append(reader.read(size))
                    reader.read(2)
                self.commands.append(args)
                conn.sendall(self._answer(args))

    def _answer(self, args):
        name = args[0].upper()
        if name == b"AUTH":
            return self.auth_reply.encode()
        if name == b"HELLO":
            return b"%0\r\n"
        if name == b"PING":
            return b"+PONG\r\n"
        if name == b"CGET":
            return b"_\r\n"
        if name == b"CSET":
            return self.cset_reply.encode()
        if name == b"CMEMEXTRACT":
            text = args[2]
            if len(text) > 65_536:
                return b"-ERR CMEMEXTRACT query is %d bytes, over the 65536 byte limit\r\n" % len(text)
            try:
                facts = _facts(text.decode("utf-8"))
            except UnicodeDecodeError:
                return b"-ERR CMEMEXTRACT text must be UTF-8\r\n"
            if len(facts) > 64:
                return (b"-ERR CMEMEXTRACT found %d facts, over the 64 one call may store: "
                        b"send the text in smaller parts\r\n" % len(facts))
            return b"*%d\r\n" % len(facts) + b"".join(_bulk(f) for f in facts)
        return b"-ERR unknown command\r\n"

    def sent(self, name):
        return [a for a in self.commands if a[0].upper() == name]


def _scripted(replies, **kwargs):
    client = CrowkisClient(**kwargs)
    sent, queue = [], list(replies)

    def execute(*args):
        sent.append([a.decode() if isinstance(a, bytes) else a for a in args])
        return queue.pop(0)

    client.execute = execute  # type: ignore[assignment]
    return client, sent


def _scripted_async(replies, **kwargs):
    client = AsyncCrowkisClient(**kwargs)
    sent, queue = [], list(replies)

    async def execute_async(*args):
        sent.append([a.decode() if isinstance(a, bytes) else a for a in args])
        return queue.pop(0)

    client.execute_async = execute_async  # type: ignore[assignment]
    return client, sent


def _warnings(logs):
    return [r.getMessage() for r in logs.records if r.levelno == logging.WARNING]


class NotStoredTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer(cset_reply=f"+NOTSTORED {PII_REASON}\r\n")
        self.addCleanup(self.server.close)
        self.client = CrowkisClient(port=self.server.port, max_retries=0)
        self.addCleanup(self.client.close)

    def test_cset_does_not_raise_and_warns_once_per_reason(self):
        with self.assertLogs("crowkis", "WARNING") as logs:
            self.assertIsNone(self.client.cset("what is my email?", "it is ana@example.com"))
            self.assertIsNone(self.client.cset("what is my email?", "it is ana@example.com"))
        said = [m for m in _warnings(logs) if "not stored" in m]
        self.assertEqual(len(said), 1, said)
        self.assertIn("personal details", said[0])
        self.assertNotIn("ana@example.com", said[0])

    def test_a_different_reason_warns_again(self):
        client, _ = _scripted(["NOTSTORED reason one", "NOTSTORED reason one", "NOTSTORED reason two"])
        with self.assertLogs("crowkis", "WARNING") as logs:
            for _ in range(3):
                client.cset("q", "a")
        said = [m for m in _warnings(logs) if "not stored" in m]
        self.assertEqual(len(said), 2, said)

    def test_get_or_compute_and_cached_still_return_the_answer(self):
        self.assertEqual(self.client.get_or_compute("q1", lambda q: "answer one"), "answer one")

        @self.client.cached()
        def model(prompt):
            return "answer two"

        self.assertEqual(model("q2"), "answer two")
        self.assertEqual(len(self.server.sent(b"CSET")), 2)

    def test_async_cset_does_not_raise_and_warns(self):
        client, _ = _scripted_async([f"NOTSTORED {PII_REASON}", None, f"NOTSTORED {PII_REASON}"])

        async def run():
            await client.cset_async("q", "a")
            return await client.get_or_compute_async("q", self._compute)

        with self.assertLogs("crowkis", "WARNING") as logs:
            self.assertEqual(asyncio.run(run()), "computed")
        self.assertEqual(len([m for m in _warnings(logs) if "not stored" in m]), 1)

    @staticmethod
    async def _compute(_):
        return "computed"

    def test_control_ok_logs_nothing(self):
        client, _ = _scripted(["OK", "OK"])
        with self.assertLogs("crowkis", "WARNING") as logs:
            logging.getLogger("crowkis").warning("marker")
            client.cset("q", "a")
            client.cset("q", "a")
        self.assertEqual(_warnings(logs), ["marker"])


class CscanTenantTests(unittest.TestCase):
    def test_client_tenant_is_sent(self):
        client, sent = _scripted([[b"0", []]], tenant="acme")
        client.cscan()
        self.assertEqual(sent, [["CSCAN", "0", "TENANT", "acme"]])

    def test_call_tenant_wins_and_options_kept(self):
        client, sent = _scripted([[b"0", []]], tenant="acme")
        client.cscan("12", match="cache:*", count=50, intent="factual", tenant="beta")
        self.assertEqual(sent, [["CSCAN", "12", "MATCH", "cache:*", "COUNT", "50", "INTENT", "factual",
                                 "TENANT", "beta"]])

    def test_no_tenant_sends_none(self):
        client, sent = _scripted([[b"0", []]])
        client.cscan()
        self.assertEqual(sent, [["CSCAN", "0"]])

    def test_numeric_cursor_iterates_to_zero(self):
        client, sent = _scripted([[b"17", [b"k1"]], [b"4096", [b"k2"]], [b"0", [b"k3"]]], tenant="acme")
        cursor, keys = "0", []
        while True:
            cursor, batch = client.cscan(cursor)
            keys += batch
            if cursor == "0":
                break
        self.assertEqual(keys, [b"k1", b"k2", b"k3"])
        self.assertEqual([s[1] for s in sent], ["0", "17", "4096"])

    def test_int_cursor_is_sent_as_digits(self):
        client, sent = _scripted([[b"0", []]])
        self.assertEqual(client.cscan(17), ("0", []))
        self.assertEqual(sent[0][:2], ["CSCAN", "17"])


class MemExtractLimitTests(unittest.TestCase):
    def setUp(self):
        self.server = FakeServer()
        self.addCleanup(self.server.close)
        self.client = CrowkisClient(port=self.server.port, max_retries=0, tenant="acme")
        self.addCleanup(self.client.close)

    def _extract_calls(self):
        return [a[2].decode("utf-8") for a in self.server.sent(b"CMEMEXTRACT")]

    def test_many_facts_are_sent_in_parts_and_combined_in_order(self):
        text = " ".join(f"I like the item numbered {i}." for i in range(200))
        facts = self.client.cmemextract("bot", text, user="ana")
        self.assertEqual(facts, [f"I like the item numbered {i}".encode() for i in range(200)])
        calls = self.server.sent(b"CMEMEXTRACT")
        self.assertGreater(len(calls), 1)
        for call in calls:
            self.assertEqual(call[3:], [b"TENANT", b"acme", b"USER", b"ana"])
            self.assertLessEqual(len(_facts(call[2].decode())), 64)

    def test_long_text_without_sentence_ends_is_cut_under_the_byte_limit(self):
        text = "my favourite note is this one " * 4000  # ~120 KB, one clause
        facts = self.client.cmemextract("bot", text)
        self.assertIsInstance(facts, list)
        self.assertTrue(facts)
        for part in self._extract_calls():
            self.assertLess(len(part.encode("utf-8")), 60 * 1024 + 1)
        self.assertEqual("".join(self._extract_calls()), text)

    def test_non_latin_text_is_cut_on_character_boundaries(self):
        text = "मेरा नाम अना है और मुझे चाय पसंद है। " * 2500  # ~200 KB of Devanagari, no "."
        self.assertIsInstance(self.client.cmemextract("bot", text), list)
        parts = self._extract_calls()
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(parts), text)

    def test_short_text_is_one_unchanged_call(self):
        text = "Hi there. I live in Pune! My name is Ana."
        self.assertEqual(self.client.cmemextract("bot", text), [b"I live in Pune", b"My name is Ana"])
        self.assertEqual(self._extract_calls(), [text])

    def test_empty_text_is_one_call(self):
        self.assertEqual(self.client.cmemextract("bot", ""), [])
        self.assertEqual(self._extract_calls(), [""])

    def test_memory_integration_extracts_long_text(self):
        text = "\n".join(f"I work at company number {i}" for i in range(150))
        mem = CrowkisMemory("bot", client=self.client, user="ana")
        self.assertEqual(len(mem.extract(text, ttl=60)), 150)
        for call in self.server.sent(b"CMEMEXTRACT"):
            self.assertEqual(call[-2:], [b"EX", b"60"])

    def test_async_extract_is_split_too(self):
        client = AsyncCrowkisClient(port=self.server.port, max_retries=0)
        text = " ".join(f"We are using tool number {i}." for i in range(130))

        async def run():
            try:
                return await client.cmemextract_async("bot", text)
            finally:
                await client.aclose()

        self.assertEqual(len(asyncio.run(run())), 130)
        self.assertGreater(len(self.server.sent(b"CMEMEXTRACT")), 1)


class AuthWithoutServerTokenTests(unittest.TestCase):
    def test_clear_error_when_server_has_no_token(self):
        server = FakeServer(auth_reply=NO_PASSWORD)
        self.addCleanup(server.close)
        client = CrowkisClient(port=server.port, token=SECRET, max_retries=2)
        with self.assertRaises(CrowkisError) as ctx:
            client.ping()
        message = str(ctx.exception)
        self.assertIn("CROWKIS_AUTH_TOKEN", message)
        self.assertIn("remove auth_token", message)
        self.assertNotIn(SECRET, message)
        self.assertEqual(len(server.sent(b"AUTH")), 1, "a configuration error is not retried")

    def test_fail_soft_reports_it_instead_of_staying_silent(self):
        server = FakeServer(auth_reply=NO_PASSWORD)
        self.addCleanup(server.close)
        seen = []
        client = CrowkisClient(port=server.port, auth_token=SECRET, fail_soft=True, on_error=seen.append)
        self.assertIsNone(client.get("k"))
        self.assertEqual(len(seen), 1)
        self.assertIn("CROWKIS_AUTH_TOKEN", str(seen[0]))

    def test_async_clear_error(self):
        server = FakeServer(auth_reply=NO_PASSWORD)
        self.addCleanup(server.close)
        client = AsyncCrowkisClient(port=server.port, token=SECRET)
        with self.assertRaisesRegex(CrowkisError, "CROWKIS_AUTH_TOKEN"):
            asyncio.run(client.execute_async("PING"))

    def test_control_wrong_token_is_still_wrongpass(self):
        server = FakeServer(auth_reply="-WRONGPASS invalid username-password pair\r\n")
        self.addCleanup(server.close)
        client = CrowkisClient(port=server.port, token=SECRET)
        with self.assertRaisesRegex(CrowkisError, "WRONGPASS"):
            client.ping()

    def test_control_matching_token_connects(self):
        server = FakeServer()
        self.addCleanup(server.close)
        client = CrowkisClient(port=server.port, token=SECRET)
        self.addCleanup(client.close)
        self.assertTrue(client.ping())


class CsetTtlZeroTests(unittest.TestCase):
    def test_ttl_zero_sends_no_ex(self):
        client, sent = _scripted(["OK", "OK", "OK"])
        client.cset("q", "a", ttl=0)
        client.cset("q", "a", ttl=None)
        client.cset("q", "a", ttl=60)
        self.assertEqual(sent, [["CSET", "q", "a"], ["CSET", "q", "a"], ["CSET", "q", "a", "EX", "60"]])

    def test_async_ttl_zero_sends_no_ex(self):
        client, sent = _scripted_async(["OK", "OK"])

        async def run():
            await client.cset_async("q", "a", ttl=0)
            await client.cset_async("q", "a", ttl=5)

        asyncio.run(run())
        self.assertEqual(sent, [["CSET", "q", "a"], ["CSET", "q", "a", "EX", "5"]])


if __name__ == "__main__":
    unittest.main()
