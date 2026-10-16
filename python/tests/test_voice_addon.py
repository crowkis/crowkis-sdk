"""Server-free tests for the Voice add-on in the SDK: the server's audio cache
(CAUDIOSET / CAUDIOGET), the fallback to the free basic path, clips stored in the
background so a caller never waits on them, and voice counts reported to the
Voice page. Run:  python -m unittest tests.test_voice_addon
"""

import threading
import time
import unittest

from crowkis.agent import Agent, _wait_for_audio_stores
from crowkis.client import CrowkisError
from crowkis.voice import VoiceSession

ADDON_MISSING = "ERR ENTERPRISE Voice is an add-on to Crowkis Enterprise. Get a licence key that includes it"


class AudioClient:
    """Stands in for a server with the Voice add-on (or without, `addon=False`)."""

    def __init__(self, addon=True, store_delay=0.0):
        self.addon = addon
        self.store_delay = store_delay
        self.clips = {}
        self.tools = {}
        self.reports = []
        self.calls = []
        self.fail_reports = False

    def caudioget(self, answer, voice, language, speed, audio_format, *, tenant=None):
        self.calls.append("caudioget")
        if not self.addon:
            raise CrowkisError(ADDON_MISSING)
        return self.clips.get((tenant, answer, voice, language, speed, audio_format))

    def caudioset(self, answer, voice, language, speed, audio_format, audio, *, ex=None, ms=None, tenant=None):
        time.sleep(self.store_delay)
        self.calls.append(("caudioset", ex, ms))
        self.clips[(tenant, answer, voice, language, speed, audio_format)] = audio

    def ctoolget(self, tool, args_str, *, tenant=None):
        self.calls.append("ctoolget")
        return self.tools.get((tool, args_str))

    def ctoolset(self, tool, args_str, result, *, ex=None, tenant=None):
        self.calls.append("ctoolset")
        self.tools[(tool, args_str)] = result.encode() if isinstance(result, str) else result

    def cvoicestat(self, counts, *, tenant=None):
        if not self.addon:
            raise CrowkisError(ADDON_MISSING)
        if self.fail_reports:
            raise CrowkisError("ERR connection reset")
        self.reports.append(dict(counts))


class SpeakTests(unittest.TestCase):
    def test_the_addon_cache_is_used_and_only_for_the_same_sound(self):
        client = AudioClient()
        agent = Agent("bot", client=client)
        made = []
        synth = lambda text: made.append(text) or b"\x00\x01audio"
        speak = lambda **kw: agent.speak("We open at nine.", synth, voice="aria", ttl=60, **kw)
        self.assertEqual(speak(audio_format="pcm16-24000", bytes_per_second=48_000), b"\x00\x01audio")
        _wait_for_audio_stores()
        self.assertEqual(speak(audio_format="pcm16-24000"), b"\x00\x01audio")
        self.assertEqual(len(made), 1, "the second time it is replayed, not synthesised")
        # Another format, language or speed: synthesised again, never reused.
        for other in [dict(audio_format="pcm16-16000"), dict(language="fr"), dict(speed="1.25")]:
            speak(**{"audio_format": "pcm16-24000", **other})
        self.assertEqual(len(made), 4)
        self.assertNotIn("ctoolset", client.calls, "the basic path is not used while the add-on answers")
        self.assertIn(("caudioset", 60, 0), client.calls, "TTL and length go with the clip")

    def test_without_the_addon_the_basic_path_is_used_and_v2_is_not_asked_again(self):
        client = AudioClient(addon=False)
        agent = Agent("bot", client=client)
        synth = lambda text: b"audio"
        agent.speak("Hello there.", synth, voice="aria")
        agent.speak("Hello there.", synth, voice="aria")
        self.assertEqual(client.calls.count("caudioget"), 1, "asked once, then the basic path")
        self.assertEqual(agent.audio_hits, 1, "the basic path still reuses the clip")

    def test_any_other_error_is_not_swallowed(self):
        class Broken(AudioClient):
            def caudioget(self, *args, **kwargs):
                raise CrowkisError("ERR tenant is paused")
        agent = Agent("bot", client=Broken())
        with self.assertRaises(CrowkisError):
            agent.speak("Hello there.", lambda text: b"audio", voice="aria")

    def test_the_caller_never_waits_for_a_clip_to_be_stored(self):
        client = AudioClient(store_delay=0.5)
        agent = Agent("bot", client=client)
        started = time.perf_counter()
        audio = agent.speak("A long answer.", lambda text: b"audio", voice="aria")
        took = time.perf_counter() - started
        self.assertEqual(audio, b"audio")
        self.assertLess(took, 0.1, f"speak waited {took:.3f}s for the store")
        _wait_for_audio_stores()
        self.assertEqual(len(client.clips), 1, "and the clip is stored all the same")


class ReviewFindingTests(unittest.TestCase):
    def test_fail_soft_without_the_addon_still_caches_the_basic_way(self):
        client = AudioClient(addon=False)
        client.fail_soft = True
        agent = Agent("bot", client=client)
        made = []
        synth = lambda text: made.append(text) or b"audio"
        for _ in range(3):
            agent.speak("Hello there.", synth, voice="aria")
        self.assertEqual(len(made), 1, "synthesised once, replayed twice")
        self.assertFalse(agent._audio_v2)

    def test_fail_soft_turns_any_other_audio_error_into_a_miss(self):
        class Down(AudioClient):
            fail_soft = True
            def caudioget(self, *args, **kwargs):
                raise CrowkisError("connection refused")
        client = Down()
        agent = Agent("bot", client=client)
        self.assertEqual(agent.speak("Hello there.", lambda text: b"audio", voice="aria"), b"audio")
        _wait_for_audio_stores()
        self.assertEqual(client.clips, {}, "nothing stored after a failed read")

    def test_no_addon_is_asked_again_after_a_while(self):
        client = AudioClient(addon=False)
        agent = Agent("bot", client=client)
        agent.speak("Hello there.", lambda text: b"audio", voice="aria")
        client.addon = True  # a licence with the add-on is installed
        agent.speak("Hello there.", lambda text: b"audio", voice="aria")
        self.assertFalse(agent._audio_v2, "not asked again at once")
        agent._audio_v2_recheck_at = time.monotonic() - 1
        agent.speak("Something new.", lambda text: b"audio", voice="aria")
        self.assertTrue(agent._audio_v2, "asked again once the wait is over")

    def test_input_the_server_would_refuse_goes_the_basic_way_without_an_error(self):
        client = AudioClient()
        agent = Agent("bot", client=client)
        for kwargs, text in [({"voice": "v" * 65}, "Hello."), ({"voice": "aria", "language": "en\nGB"}, "Hello."),
                             ({"voice": "aria"}, "x" * (64 * 1024 + 1)), ({"voice": "aria"}, "")]:
            agent.speak(text, lambda t: b"audio", **kwargs)
        self.assertNotIn("caudioget", client.calls)
        self.assertIn("ctoolset", client.calls)

    def test_only_the_servers_enterprise_refusal_means_no_addon(self):
        from crowkis.agent import _voice_addon_missing
        self.assertTrue(_voice_addon_missing(CrowkisError("ERR ENTERPRISE Voice is an add-on")))
        self.assertTrue(_voice_addon_missing(CrowkisError("ERR unknown command 'CAUDIOGET'")))
        self.assertFalse(_voice_addon_missing(CrowkisError("ERR the add-on store is full")))
        self.assertFalse(_voice_addon_missing(CrowkisError("ERR tenant ENTERPRISE-1 is paused")))


class ReportTests(unittest.TestCase):
    def session(self, client):
        return VoiceSession(Agent("bot", client=client), voice="aria")

    def test_reports_send_what_is_new_and_lose_nothing_when_one_fails(self):
        client = AudioClient()
        s = self.session(client)
        s.served, s.inferred, s.filled, s.barge_ins = 3, 2, 1, 4
        self.assertTrue(s.report_stats())
        self.assertEqual(client.reports[-1], {
            "turns": 6, "served_from_cache": 3, "filler_hits": 1, "model_calls_avoided": 4, "barge_ins": 4,
        })
        self.assertTrue(s.report_stats(), "nothing new: nothing sent")
        self.assertEqual(len(client.reports), 1)
        s.served += 2
        client.fail_reports = True
        with self.assertRaises(CrowkisError):
            s.report_stats()
        client.fail_reports = False
        self.assertTrue(s.report_stats())
        self.assertEqual(client.reports[-1], {"turns": 2, "served_from_cache": 2, "model_calls_avoided": 2},
                         "the failed report's counts went with the next one")

    def test_without_the_addon_a_report_says_so(self):
        s = self.session(AudioClient(addon=False))
        s.served = 1
        self.assertFalse(s.report_stats())

    def test_one_report_never_exceeds_what_the_server_takes(self):
        client = AudioClient()
        s = self.session(client)
        s.served = 2_500_000
        for _ in range(5):
            self.assertTrue(s.report_stats())
        sent = sum(r.get("served_from_cache", 0) for r in client.reports)
        self.assertEqual(sent, 2_500_000)
        self.assertTrue(all(r["served_from_cache"] <= 1_000_000 for r in client.reports))


if __name__ == "__main__":
    unittest.main()
