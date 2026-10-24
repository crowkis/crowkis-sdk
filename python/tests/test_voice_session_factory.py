"""crowkis.voice_session(): a ready VoiceSession in one call, with live-call defaults.

It builds the client and the Agent itself (server settings from the environment, as any
client), with a 250 ms lookup budget, a 1 s server timeout and no retries, so a stuck
server costs a turn about a second instead of ~15 s. `voice` is optional: without it the
session caches text only and never reads or stores audio, so two TTS voices can never
share a clip. VoiceSession(...) itself is unchanged."""

import asyncio
import os
import socket
import threading
import time
import unittest
from unittest import mock

import crowkis
from crowkis import Agent, CrowkisClient, VoiceSession

from test_voice_stress_bugs import _pipecat

_NAMES = ("CROWKIS_HOST", "CROWKIS_PORT", "CROWKIS_AUTH_TOKEN", "CROWKIS_TOKEN",
          "CROWKIS_TENANT", "CROWKIS_URL")


def _env(**values):
    clean = {k: v for k, v in os.environ.items() if k not in _NAMES}
    clean.update(values)
    return mock.patch.dict(os.environ, clean, clear=True)


class _Untouchable:
    """A client that fails the test if anything is sent through it."""

    tenant = None
    fail_soft = False

    def __getattr__(self, name):
        raise AssertionError(f"the server was asked: {name}")


class DefaultsTests(unittest.TestCase):
    def test_exported_at_top_level_and_from_the_voice_module(self):
        from crowkis.voice import voice_session

        self.assertIs(crowkis.voice_session, voice_session)
        self.assertIn("voice_session", crowkis.__all__)

    def test_the_voice_module_is_still_the_module(self):
        import crowkis.voice as module

        self.assertTrue(hasattr(module, "VoiceSession"))
        self.assertIs(crowkis.voice, module)

    def test_one_call_gives_a_ready_session_with_live_call_defaults(self):
        with _env():
            session = crowkis.voice_session()
        self.assertIsInstance(session, VoiceSession)
        self.assertEqual(session.latency_budget_ms, 250)
        self.assertEqual(session.agent.agent_id, "voice")
        client = session.agent._client
        self.assertEqual((client.host, client.port), ("127.0.0.1", 6383))
        self.assertEqual((client.connect_timeout, client.read_timeout), (1.0, 1.0))
        self.assertEqual(client.max_retries, 0)
        self.assertFalse(client.fail_soft)

    def test_server_settings_come_from_the_environment(self):
        with _env(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_AUTH_TOKEN="tok",
                  CROWKIS_TENANT="my-app"):
            session = crowkis.voice_session()
        client = session.agent._client
        self.assertEqual((client.host, client.port, client.auth_token, client.tenant),
                         ("10.0.0.5", 6390, "tok", "my-app"))
        self.assertEqual(session.agent.tenant, "my-app")

    def test_server_settings_passed_in_code_win(self):
        with _env(CROWKIS_HOST="10.0.0.5", CROWKIS_PORT="6390", CROWKIS_TENANT="env"):
            session = crowkis.voice_session(host="h", port=7000, auth_token="t", tenant="code")
        client = session.agent._client
        self.assertEqual((client.host, client.port, client.auth_token, client.tenant),
                         ("h", 7000, "t", "code"))
        self.assertEqual(session.agent.tenant, "code")

    def test_defaults_can_be_changed(self):
        with _env():
            session = crowkis.voice_session(agent_id="support", latency_budget_ms=400, timeout=2.5)
        self.assertEqual(session.agent.agent_id, "support")
        self.assertEqual(session.latency_budget_ms, 400)
        self.assertEqual(session.agent._client.read_timeout, 2.5)

    def test_token_is_accepted_as_in_the_client(self):
        with _env():
            self.assertEqual(crowkis.voice_session(token="t").agent._client.auth_token, "t")

    def test_a_timeout_that_is_not_positive_is_refused(self):
        with _env():
            for bad in (0, -1):
                with self.subTest(timeout=bad), self.assertRaises(ValueError) as caught:
                    crowkis.voice_session(timeout=bad)
                self.assertIn("timeout", str(caught.exception))

    def test_the_budget_can_be_turned_off(self):
        with _env():
            self.assertIsNone(crowkis.voice_session(latency_budget_ms=None).latency_budget_ms)

    def test_every_other_voice_session_option_is_passed_on(self):
        with _env():
            session = crowkis.voice_session(
                serve_above=0.95, min_words=4, ttl=60, fillers={"hello": "Hi, how can I help?"},
                commitments="never", language="hi", speed="1.1",
            )
        self.assertEqual((session.serve_above, session.min_words, session.ttl), (0.95, 4, 60))
        self.assertEqual((session.commitments, session.language, session.speed), ("never", "hi", "1.1"))
        self.assertEqual(session.decide("hello").action, "filler")

    def test_an_unknown_option_is_an_error(self):
        with _env(), self.assertRaises(TypeError):
            crowkis.voice_session(serve_abov=0.9)

    def test_closing_the_agent_closes_the_client_it_made(self):
        with _env():
            session = crowkis.voice_session()
        with mock.patch.object(session.agent._client, "close") as close:
            session.agent.close()
        close.assert_called_once()


class OwnClientTests(unittest.TestCase):
    def test_a_client_passed_in_is_used_as_it_is(self):
        client = CrowkisClient(host="h", port=7000, timeout=9.0, max_retries=3, tenant="t")
        session = crowkis.voice_session(client=client)
        self.assertIs(session.agent._client, client)
        self.assertEqual((client.read_timeout, client.max_retries), (9.0, 3))
        self.assertEqual(session.agent.tenant, "t")

    def test_a_client_passed_in_is_not_closed_with_the_agent(self):
        client = CrowkisClient()
        session = crowkis.voice_session(client=client)
        with mock.patch.object(client, "close") as close:
            session.agent.close()
        close.assert_not_called()

    def test_server_settings_next_to_a_client_are_refused(self):
        client = CrowkisClient()
        for extra in ({"host": "h"}, {"port": 1}, {"auth_token": "t"}, {"token": "t"},
                      {"tenant": "t"}, {"timeout": 2.0}):
            with self.subTest(extra=extra), self.assertRaises(ValueError) as caught:
                crowkis.voice_session(client=client, **extra)
            self.assertIn("client", str(caught.exception))


class VoiceIdTests(unittest.TestCase):
    def test_a_voice_turns_audio_caching_on(self):
        synth = lambda text: b"pcm"  # noqa: E731
        with _env():
            session = crowkis.voice_session(voice="eleven-rachel", synthesise=synth)
        self.assertEqual(session.voice, "eleven-rachel")
        self.assertIs(session.synthesise, synth)

    def test_synthesise_without_a_voice_is_refused(self):
        with _env(), self.assertRaises(ValueError) as caught:
            crowkis.voice_session(synthesise=lambda text: b"pcm")
        self.assertIn("voice", str(caught.exception))

    def test_an_empty_voice_is_refused_as_before(self):
        with _env():
            for blank in ("", "   "):
                with self.subTest(voice=blank), self.assertRaises(ValueError):
                    crowkis.voice_session(voice=blank)

    def test_the_old_constructor_still_requires_a_voice(self):
        agent = Agent("support", client=_Untouchable())
        with self.assertRaises(ValueError):
            VoiceSession(agent, voice="")


class TextOnlyTests(unittest.TestCase):
    """Without a voice no audio is ever read or stored, even if a synthesiser is added
    later: a clip stored under a made-up voice would play in whatever voice asked."""

    def session(self):
        with _env():
            session = crowkis.voice_session()
        session.agent._client = _Untouchable()
        return session

    def test_a_synthesiser_added_later_is_used_but_never_cached(self):
        session = self.session()
        session.synthesise = lambda text: b"fresh:" + text.encode()
        with mock.patch.object(session.agent, "speak", side_effect=AssertionError("cached")):
            self.assertEqual(session._voiced("Refunds take five days."), b"fresh:Refunds take five days.")

    def test_no_synthesiser_means_no_audio(self):
        self.assertIsNone(self.session()._voiced("Refunds take five days."))

    def test_pipecat_audio_cache_never_reads_or_stores(self):
        pc, _, _ = _pipecat()
        session = self.session()
        audio = pc.CrowkisAudioCache(session, sample_rate=16000)

        async def run():
            self.assertIsNone(await audio.get("Refunds take five days."))
            await audio._store("Refunds take five days.", b"\x00\x01" * 800)

        asyncio.run(run())

    def test_a_session_with_a_voice_still_uses_the_audio_cache(self):
        pc, _, _ = _pipecat()
        with _env():
            session = crowkis.voice_session(voice="eleven-rachel")
        session.agent._client = _Untouchable()
        audio = pc.CrowkisAudioCache(session, sample_rate=16000)
        with self.assertRaises(AssertionError):  # it asked the server for the clip
            asyncio.run(audio.get("Refunds take five days."))


class StuckServerTests(unittest.TestCase):
    """A server that accepts connections and never answers: the turn goes to the model
    within the budget, and saving the answer gives up after the 1 s timeout."""

    def test_a_stuck_server_costs_a_turn_about_a_second(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        held = []
        stop = threading.Event()

        def accept():
            listener.settimeout(0.2)
            while not stop.is_set():
                try:
                    held.append(listener.accept()[0])  # read nothing, answer nothing
                except OSError:
                    continue

        thread = threading.Thread(target=accept, daemon=True)
        thread.start()
        try:
            with _env(CROWKIS_PORT=str(listener.getsockname()[1])):
                session = crowkis.voice_session()
            started = time.monotonic()
            decision = session.answer(
                "how long do refunds usually take to arrive",
                lambda messages: "Refunds arrive within five business days of approval.",
            )
            took = time.monotonic() - started
        finally:
            stop.set()
            thread.join(2)
            for conn in held:
                conn.close()
            listener.close()
        self.assertTrue(held, "the turn never reached the server, so this proves nothing")
        self.assertEqual(decision.text, "Refunds arrive within five business days of approval.")
        self.assertFalse(decision.stored)
        self.assertGreater(session.over_budget + session.lookup_errors, 0)
        # The save was tried; the turn stopped waiting for it at the latency budget (it
        # gives up in the background). Was: the turn waited the client's 1 s timeout.
        self.assertEqual(session.slow_writes, 1)
        self.assertLess(took, 1.0)


if __name__ == "__main__":
    unittest.main()
