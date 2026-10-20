"""Server settings from the environment (Crowkis 0.5.2).

A value passed in code wins, then CROWKIS_HOST / CROWKIS_PORT / CROWKIS_AUTH_TOKEN
(or CROWKIS_TOKEN) / CROWKIS_TENANT, then the parts of CROWKIS_URL, then the built-in
default (127.0.0.1:6383, no token, no tenant). Every class that builds its own client
follows the same rule, and the token never shows up in a repr or an error."""

import os
import socket
import threading
import traceback
import unittest
from unittest import mock

from crowkis import Agent, AsyncCrowkisClient, CrowkisClient, CrowkisMemory
from crowkis.openai_wrapper import CachedOpenAI

SECRET = "tok-env-9c2e-very-secret"

_NAMES = (
    "CROWKIS_HOST",
    "CROWKIS_PORT",
    "CROWKIS_AUTH_TOKEN",
    "CROWKIS_TOKEN",
    "CROWKIS_TENANT",
    "CROWKIS_URL",
)


def _env(**values):
    """os.environ with every CROWKIS_* setting cleared, then `values` set."""
    clean = {k: v for k, v in os.environ.items() if k not in _NAMES}
    clean.update(values)
    return mock.patch.dict(os.environ, clean, clear=True)


def _settings(client):
    return client.host, client.port, client.auth_token, client.tenant


class DefaultsTests(unittest.TestCase):
    def test_nothing_set_keeps_todays_defaults(self):
        with _env():
            self.assertEqual(_settings(CrowkisClient()), ("127.0.0.1", 6383, None, None))

    def test_empty_and_blank_variables_count_as_not_set(self):
        with _env(CROWKIS_HOST="", CROWKIS_PORT="  ", CROWKIS_AUTH_TOKEN="", CROWKIS_TENANT=" ",
                  CROWKIS_URL=""):
            self.assertEqual(_settings(CrowkisClient()), ("127.0.0.1", 6383, None, None))


class EnvironmentTests(unittest.TestCase):
    def test_each_variable_is_used_when_nothing_is_passed(self):
        with _env(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_AUTH_TOKEN=SECRET,
                  CROWKIS_TENANT="my-app"):
            self.assertEqual(_settings(CrowkisClient()), ("10.0.0.5", 6390, SECRET, "my-app"))

    def test_surrounding_whitespace_is_ignored(self):
        with _env(CROWKIS_HOST=" 10.0.0.5 ", CROWKIS_PORT=" 6390\n"):
            client = CrowkisClient()
            self.assertEqual((client.host, client.port), ("10.0.0.5", 6390))

    def test_crowkis_token_is_accepted(self):
        with _env(CROWKIS_TOKEN=SECRET):
            self.assertEqual(CrowkisClient().auth_token, SECRET)

    def test_crowkis_auth_token_wins_over_crowkis_token(self):
        with _env(CROWKIS_AUTH_TOKEN=SECRET, CROWKIS_TOKEN="other"):
            self.assertEqual(CrowkisClient().auth_token, SECRET)

    def test_read_when_the_client_is_created_not_at_import(self):
        with _env():
            before = CrowkisClient()
        with _env(CROWKIS_PORT="6391"):
            after = CrowkisClient()
        self.assertEqual((before.port, after.port), (6383, 6391))

    def test_async_client_reads_the_environment_too(self):
        with _env(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_TENANT="my-app"):
            client = AsyncCrowkisClient()
            self.assertEqual((client.host, client.port, client.tenant), ("10.0.0.5", 6390, "my-app"))


class CodeWinsTests(unittest.TestCase):
    ENV = dict(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_AUTH_TOKEN="from-env",
               CROWKIS_TENANT="env-tenant")

    def test_every_value_passed_in_code_wins(self):
        with _env(**self.ENV):
            client = CrowkisClient(host="h", port=7000, auth_token="from-code", tenant="code-tenant")
            self.assertEqual(_settings(client), ("h", 7000, "from-code", "code-tenant"))

    def test_positional_host_and_port_still_work_and_win(self):
        with _env(**self.ENV):
            client = CrowkisClient("h", 7000)
            self.assertEqual((client.host, client.port), ("h", 7000))

    def test_token_keyword_wins_over_the_environment(self):
        with _env(**self.ENV):
            self.assertEqual(CrowkisClient(token="from-code").auth_token, "from-code")

    def test_a_value_in_code_only_replaces_that_one_setting(self):
        with _env(**self.ENV):
            self.assertEqual(_settings(CrowkisClient(port=7000)),
                             ("10.0.0.5", 7000, "from-env", "env-tenant"))


class UrlTests(unittest.TestCase):
    def test_full_url(self):
        with _env(CROWKIS_URL=f"crowkis://:{SECRET}@10.0.0.5:6390/my-app"):
            self.assertEqual(_settings(CrowkisClient()), ("10.0.0.5", 6390, SECRET, "my-app"))

    def test_partial_url_falls_back_to_defaults(self):
        with _env(CROWKIS_URL="crowkis://10.0.0.5"):
            self.assertEqual(_settings(CrowkisClient()), ("10.0.0.5", 6383, None, None))

    def test_separate_variables_win_over_url_parts(self):
        with _env(CROWKIS_URL=f"crowkis://:{SECRET}@10.0.0.5:6390/my-app",
                  CROWKIS_PORT="6391", CROWKIS_TENANT="other"):
            self.assertEqual(_settings(CrowkisClient()), ("10.0.0.5", 6391, SECRET, "other"))

    def test_code_wins_over_url(self):
        with _env(CROWKIS_URL="crowkis://10.0.0.5:6390/my-app"):
            self.assertEqual(_settings(CrowkisClient(host="h", port=7000, tenant="t")),
                             ("h", 7000, None, "t"))

    def test_ipv6_host(self):
        with _env(CROWKIS_URL="crowkis://[::1]:6390"):
            client = CrowkisClient()
            self.assertEqual((client.host, client.port), ("::1", 6390))


class BadValueTests(unittest.TestCase):
    def assert_names(self, variable, **values):
        with _env(**values):
            with self.assertRaises(ValueError) as caught:
                CrowkisClient()
        self.assertIn(variable, str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_port_that_is_not_a_number(self):
        self.assert_names("CROWKIS_PORT", CROWKIS_PORT="abc")

    def test_port_out_of_range(self):
        self.assert_names("CROWKIS_PORT", CROWKIS_PORT="0")
        self.assert_names("CROWKIS_PORT", CROWKIS_PORT="70000")

    def test_url_with_another_scheme(self):
        self.assert_names("CROWKIS_URL", CROWKIS_URL=f"http://:{SECRET}@10.0.0.5:6390")

    def test_url_with_a_bad_port_never_echoes_the_token(self):
        self.assert_names("CROWKIS_URL", CROWKIS_URL=f"crowkis://:{SECRET}@10.0.0.5:99999")

    def test_url_with_no_host(self):
        self.assert_names("CROWKIS_URL", CROWKIS_URL=f"crowkis://:{SECRET}@:6390")

    def test_port_must_be_plain_ascii_digits(self):
        for text in ("6_383", "+80", "63.5", "٦٣٨٣"):
            self.assert_names("CROWKIS_PORT", CROWKIS_PORT=text)

    def test_url_port_zero(self):
        self.assert_names("CROWKIS_URL", CROWKIS_URL="crowkis://10.0.0.5:0")

    def test_an_unreadable_url_carries_the_token_nowhere(self):
        # A redis-style URL with no @: the parser reads the token as the port and
        # quotes it in its own error. None of that may travel with ours.
        # assertRaises drops the traceback, so catch by hand: an error tracker sees
        # the SDK's frames and their local variables.
        for url in (f"crowkis://default:{SECRET}", f"crowkis://[::1:{SECRET}"):
            err = None
            with _env(CROWKIS_URL=url):
                try:
                    CrowkisClient()
                except ValueError as raised:
                    err = raised
            self.assertIsNotNone(err)
            self.assertIn("CROWKIS_URL", str(err))
            self.assertIsNone(err.__cause__)
            self.assertIsNone(err.__context__)
            self.assertNotIn(SECRET, "".join(traceback.format_exception(err)))
            frame = err.__traceback__.tb_next  # skip this test's own frame
            self.assertIsNotNone(frame)
            while frame is not None:
                for value in frame.tb_frame.f_locals.values():
                    try:
                        shown = repr(value)
                    except Exception:  # a half-built client cannot print itself
                        continue
                    self.assertNotIn(SECRET, shown)
                frame = frame.tb_next

    def test_a_bad_variable_is_ignored_when_code_passes_that_value(self):
        with _env(CROWKIS_PORT="abc"):
            self.assertEqual(CrowkisClient(port=7000).port, 7000)


class UnchangedWithoutEnvironmentTests(unittest.TestCase):
    """With no CROWKIS_* variable set, every constructor gives what it gave before."""

    def test_explicit_odd_values_pass_through_as_before(self):
        with _env():
            client = CrowkisClient(host="", port=0, token="", tenant="")
            self.assertEqual(_settings(client), ("", 0, None, ""))

    def test_wrappers_built_with_no_arguments_keep_the_old_defaults(self):
        with _env():
            want = ("127.0.0.1", 6383, None, None)
            self.assertEqual(_settings(Agent("support")._client), want)
            self.assertEqual(_settings(CrowkisMemory("support").client), want)
            self.assertEqual(_settings(CachedOpenAI(openai_client=object())._crowkis), want)

    def test_an_empty_token_or_tenant_in_code_counts_as_not_passed(self):
        with _env(CROWKIS_AUTH_TOKEN=SECRET, CROWKIS_TENANT="env-tenant"):
            client = CrowkisClient(token="", tenant="")
            self.assertEqual((client.auth_token, client.tenant), (SECRET, "env-tenant"))


class UrlDetailTests(unittest.TestCase):
    def resolve(self, url):
        with _env(CROWKIS_URL=url):
            return _settings(CrowkisClient())

    def test_percent_encoded_token_and_tenant(self):
        self.assertEqual(self.resolve("crowkis://:a%20b%40c@h/t%2Fx"), ("h", 6383, "a b@c", "t/x"))

    def test_token_given_as_the_user_part(self):
        self.assertEqual(self.resolve("crowkis://only-token@h:6390"), ("h", 6390, "only-token", None))

    def test_uppercase_scheme_query_and_fragment(self):
        self.assertEqual(self.resolve("CROWKIS://h:6390/my-app?x=1#y"), ("h", 6390, None, "my-app"))

    def test_an_escape_that_cannot_be_decoded_is_kept_as_written(self):
        self.assertEqual(self.resolve("crowkis://:%zz@h")[2], "%zz")
        self.assertEqual(self.resolve("crowkis://:%E0%A4%A@h")[2], "%E0%A4%A")
        self.assertEqual(self.resolve("crowkis://:%E0%A4%A4x%FF@h")[2], "तx%FF")


class SecretTests(unittest.TestCase):
    def test_token_from_the_environment_is_never_printed(self):
        with _env(CROWKIS_AUTH_TOKEN=SECRET, CROWKIS_URL=f"crowkis://:{SECRET}@10.0.0.5"):
            client = CrowkisClient()
            self.assertNotIn(SECRET, repr(client))
            self.assertNotIn(SECRET, str(client))


class WrapperTests(unittest.TestCase):
    """Classes that build their own client follow the same rule."""

    ENV = dict(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_AUTH_TOKEN=SECRET,
               CROWKIS_TENANT="my-app")

    def test_agent(self):
        with _env(**self.ENV):
            self.assertEqual(_settings(Agent("support")._client), ("10.0.0.5", 6390, SECRET, "my-app"))

    def test_agent_code_wins(self):
        with _env(**self.ENV):
            client = Agent("support", host="h", port=7000, auth_token="c", tenant="t")._client
            self.assertEqual(_settings(client), ("h", 7000, "c", "t"))

    def test_memory(self):
        with _env(**self.ENV):
            self.assertEqual(_settings(CrowkisMemory("support").client),
                             ("10.0.0.5", 6390, SECRET, "my-app"))

    def test_memory_code_wins(self):
        with _env(**self.ENV):
            client = CrowkisMemory("support", host="h", port=7000).client
            self.assertEqual((client.host, client.port), ("h", 7000))

    def test_langchain_cache(self):
        try:
            from crowkis.integrations.langchain import CrowkisCache
        except ImportError:
            self.skipTest("langchain-core not installed")
        with _env(**self.ENV):
            self.assertEqual(_settings(CrowkisCache().client), ("10.0.0.5", 6390, SECRET, "my-app"))
            self.assertEqual(CrowkisCache(port=7000).client.port, 7000)

    def test_openai_wrapper(self):
        with _env(**self.ENV):
            client = CachedOpenAI(openai_client=object())._crowkis
            self.assertEqual(_settings(client), ("10.0.0.5", 6390, SECRET, "my-app"))

    def test_openai_wrapper_code_wins(self):
        with _env(**self.ENV):
            client = CachedOpenAI(crowkis_host="h", crowkis_port=7000, openai_client=object())._crowkis
            self.assertEqual((client.host, client.port), ("h", 7000))


class OverTheWireTests(unittest.TestCase):
    """The settings reach the server: the token is sent as AUTH and the tenant goes on
    the commands of an Agent built with no arguments."""

    def _frames(self, make, call):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        received = bytearray()

        def serve():
            try:
                conn, _ = listener.accept()
            except OSError:  # nobody connected; the test's assertions report it
                return
            with conn:
                while b"CMEMSET" not in received and b"PING" not in received:
                    chunk = conn.recv(4096)
                    if not chunk:
                        return
                    received.extend(chunk)
                    conn.sendall(b"+OK\r\n" * chunk.count(b"*"))

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        try:
            with _env(CROWKIS_HOST="127.0.0.1", CROWKIS_PORT=str(listener.getsockname()[1]),
                      CROWKIS_AUTH_TOKEN=SECRET, CROWKIS_TENANT="env-tenant"):
                made = make()
            call(made)
        finally:
            thread.join(2)
            listener.close()
        return bytes(received)

    def test_client_sends_the_token_from_the_environment(self):
        def call(client):
            try:
                client.execute("PING")
            finally:
                client.close()

        frames = self._frames(lambda: CrowkisClient(max_retries=0), call)
        self.assertTrue(frames.startswith(b"*2\r\n$4\r\nAUTH\r\n"))
        self.assertIn(SECRET.encode(), frames)

    def test_agent_puts_the_environment_tenant_on_its_commands(self):
        def call(agent):
            try:
                agent.remember("prefers email")
            finally:
                agent.close()

        frames = self._frames(lambda: Agent("support"), call)
        self.assertIn(b"CMEMSET", frames)
        self.assertIn(b"env-tenant", frames)


if __name__ == "__main__":
    unittest.main()
