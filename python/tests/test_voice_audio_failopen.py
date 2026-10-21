"""Audio never breaks a call, and a clip is only reused for the sound it was made for.

- Agent.speak(): an audio cache read or write that fails is a miss: the clip is made
  (synthesise) and returned, the failure logged and counted (agent.audio_errors).
  Before, a failed read raised and a failed basic-path write lost the clip just made.
- VoiceSession: when the audio step fails for any reason (the cache, or the app's own
  synthesiser), the turn still gets its text, with no audio (stats()["audio_unavailable"]).
  Before, the whole turn raised and the cached answer was lost.
- The basic audio cache key now names language, speed and format when they are not the
  defaults, so a clip made for one format is never played for another. With the defaults
  the key is unchanged, so existing clips stay valid. Pipecat names its sample rate."""

import asyncio
import json
import unittest

from crowkis import Agent, CrowkisError, VoiceSession
from crowkis.agent import _tts_key, _wait_for_audio_stores

from test_voice_stress_bugs import ANSWER, Store, _pipecat

PCM = b"\x01\x02" * 400


class AudioServer:
    """A client with the audio commands; each can be told to fail."""

    def __init__(self, *, v2=True, fail=()):
        self.v2 = v2
        self.fail = set(fail)
        self.tool = {}
        self.audio = {}
        self.calls = []
        self.tenant = None
        self.fail_soft = False

    def _maybe_fail(self, name):
        self.calls.append(name)
        if name in self.fail:
            raise CrowkisError(f"ERR {name} failed: connection reset")

    def caudioget(self, text, *labels, tenant=None):
        if not self.v2:
            self.calls.append("caudioget")
            raise CrowkisError("ERR unknown command 'CAUDIOGET' (Voice add-on not licensed)")
        self._maybe_fail("caudioget")
        return self.audio.get((text, labels))

    def caudioset(self, text, *labels_and_clip, ex=None, ms=None, tenant=None):
        self._maybe_fail("caudioset")
        *labels, clip = labels_and_clip
        self.audio[(text, tuple(labels))] = clip

    def ctoolget(self, tool, key, tenant=None):
        self._maybe_fail("ctoolget")
        return self.tool.get(key)

    def ctoolset(self, tool, key, value, ex=None, tenant=None):
        self._maybe_fail("ctoolset")
        self.tool[key] = value


def synth(text):
    return PCM


class SpeakTests(unittest.TestCase):
    def test_a_failed_audio_cache_read_is_a_miss_not_an_error(self):
        server = AudioServer(fail={"caudioget"})
        agent = Agent("a", client=server)
        self.assertEqual(agent.speak(ANSWER, synth, voice="v"), PCM)
        self.assertNotIn("caudioset", server.calls)  # the cache just failed: don't wait on it again
        self.assertEqual(agent.audio_errors, 1)

    def test_a_failed_basic_read_is_a_miss_not_an_error(self):
        server = AudioServer(v2=False, fail={"ctoolget"})
        agent = Agent("a", client=server)
        self.assertEqual(agent.speak(ANSWER, synth, voice="v"), PCM)
        self.assertNotIn("ctoolset", server.calls)
        self.assertEqual(agent.audio_errors, 1)

    def test_a_failed_basic_write_still_returns_the_clip_just_made(self):
        server = AudioServer(v2=False, fail={"ctoolset"})
        agent = Agent("a", client=server)
        self.assertEqual(agent.speak(ANSWER, synth, voice="v"), PCM)
        self.assertEqual(agent.audio_errors, 1)

    def test_no_voice_add_on_still_uses_the_basic_cache(self):
        server = AudioServer(v2=False)
        agent = Agent("a", client=server)
        agent.speak(ANSWER, synth, voice="v")
        self.assertIn("ctoolset", server.calls)
        self.assertEqual(agent.speak(ANSWER, lambda t: self.fail("synthesised again"), voice="v"), PCM)
        self.assertEqual(agent.audio_errors, 0)

    def test_a_synthesiser_error_is_still_the_apps_to_handle(self):
        agent = Agent("a", client=AudioServer())

        def broken(text):
            raise RuntimeError("TTS down")

        with self.assertRaises(RuntimeError):
            agent.speak(ANSWER, broken, voice="v")


class KeyTests(unittest.TestCase):
    def test_the_default_key_is_unchanged_so_existing_clips_stay_valid(self):
        old = json.dumps({"voice": "v", "text": ANSWER}, sort_keys=True)
        self.assertEqual(_tts_key(ANSWER, ("v", "und", "1", "default")), old)

    def test_a_clip_is_keyed_by_what_changes_its_sound(self):
        base = ("v", "und", "1", "default")
        keys = {
            _tts_key(ANSWER, base),
            _tts_key(ANSWER, ("v", "und", "1", "pcm16-8000")),
            _tts_key(ANSWER, ("v", "und", "1", "pcm16-24000")),
            _tts_key(ANSWER, ("v", "hi", "1", "default")),
            _tts_key(ANSWER, ("v", "und", "1.2", "default")),
        }
        self.assertEqual(len(keys), 5)

    def test_speak_reuses_a_basic_clip_only_for_the_same_format(self):
        server = AudioServer(v2=False)
        agent = Agent("a", client=server)
        agent.speak(ANSWER, lambda t: b"8k", voice="v", audio_format="pcm16-8000")
        self.assertEqual(agent.speak(ANSWER, lambda t: b"24k", voice="v", audio_format="pcm16-24000"), b"24k")
        self.assertEqual(agent.speak(ANSWER, lambda t: self.fail("again"), voice="v", audio_format="pcm16-8000"), b"8k")

    def test_pipecat_keys_name_the_sample_rate(self):
        pc, _, _ = _pipecat()
        session = VoiceSession(Agent("a", client=AudioServer(v2=False)), voice="v")
        k16 = pc.CrowkisAudioCache(session, sample_rate=16000)._key(ANSWER)
        k24 = pc.CrowkisAudioCache(session, sample_rate=24000)._key(ANSWER)
        self.assertNotEqual(k16, k24)
        self.assertIn("pcm16-16000", k16)


class SessionTests(unittest.TestCase):
    def store_with_answer(self, client_cls=Store):
        store = client_cls()
        store.shared["what is your refund policy"] = ANSWER
        return store

    def test_a_cache_hit_whose_audio_fails_still_serves_the_text(self):
        class FailingAudioStore(Store):
            def caudioget(self, *args, **kwargs):
                raise CrowkisError("ERR connection reset")

        session = VoiceSession(Agent("a", client=self.store_with_answer(FailingAudioStore)), voice="v",
                               synthesise=lambda t: (_ for _ in ()).throw(RuntimeError("TTS down")))
        decision = session.decide("what is your refund policy")
        self.assertEqual((decision.action, decision.text, decision.audio), ("serve", ANSWER, None))
        self.assertEqual(session.stats()["audio_unavailable"], 1)

    def test_the_apps_synthesiser_failing_still_serves_the_text(self):
        def broken(text):
            raise RuntimeError("TTS down")

        session = VoiceSession(Agent("a", client=self.store_with_answer()), voice="v", synthesise=broken)
        decision = session.decide("what is your refund policy")
        self.assertEqual((decision.action, decision.text, decision.audio), ("serve", ANSWER, None))

    def test_a_filler_whose_audio_fails_still_answers(self):
        def broken(text):
            raise RuntimeError("TTS down")

        session = VoiceSession(Agent("a", client=Store()), voice="v", synthesise=broken,
                               fillers={"hello": "Hi, how can I help?"})
        decision = session.decide("hello")
        self.assertEqual((decision.action, decision.text, decision.audio), ("filler", "Hi, how can I help?", None))

    def test_answer_and_respond_keep_working_when_audio_fails(self):
        def broken(text):
            raise RuntimeError("TTS down")

        session = VoiceSession(Agent("a", client=self.store_with_answer()), voice="v", synthesise=broken)
        self.assertEqual(session.answer("what is your refund policy", lambda m: self.fail("model")).text, ANSWER)
        self.assertEqual(list(session.respond("what is your refund policy", lambda m: self.fail("model"))), [ANSWER])

    def test_audio_that_works_is_unchanged(self):
        session = VoiceSession(Agent("a", client=self.store_with_answer()), voice="v", synthesise=synth)
        decision = session.decide("what is your refund policy")
        self.assertEqual(decision.audio, PCM)
        self.assertEqual(session.stats()["audio_unavailable"], 0)


class PipecatTests(unittest.TestCase):
    def test_a_failed_audio_cache_read_is_a_miss_in_pipecat(self):
        pc, _, _ = _pipecat()
        server = AudioServer(fail={"caudioget"})
        session = VoiceSession(Agent("a", client=server), voice="v")
        audio = pc.CrowkisAudioCache(session, sample_rate=16000)
        self.assertIsNone(asyncio.run(audio.get(ANSWER)))

    def test_a_failed_basic_read_or_write_is_a_miss_in_pipecat(self):
        pc, _, _ = _pipecat()
        server = AudioServer(v2=False, fail={"ctoolget", "ctoolset"})
        session = VoiceSession(Agent("a", client=server), voice="v")
        audio = pc.CrowkisAudioCache(session, sample_rate=16000)
        self.assertIsNone(asyncio.run(audio.get(ANSWER)))
        asyncio.run(audio._store(ANSWER, PCM))
        _wait_for_audio_stores()  # the clip is stored in the background (c20ee2a)
        self.assertEqual(session.agent.audio_errors, 2)

    def test_the_read_miss_reaches_decide_with_a_working_synthesiser(self):
        class FailingAudioStore(Store):
            def caudioget(self, *args, **kwargs):
                raise CrowkisError("ERR connection reset")

        store = FailingAudioStore()
        store.shared["what is your refund policy"] = ANSWER
        session = VoiceSession(Agent("a", client=store), voice="v", synthesise=synth)
        decision = session.decide("what is your refund policy")
        self.assertEqual((decision.action, decision.audio), ("serve", PCM))  # made fresh
        self.assertEqual(session.agent.audio_errors, 1)
        self.assertEqual(session.stats()["audio_unavailable"], 0)

    def test_the_log_never_quotes_the_answer(self):
        def broken(text):
            raise RuntimeError(f"TTS could not say: {text}")

        session = VoiceSession(Agent("a", client=Store()), voice="v", synthesise=broken,
                               fillers={"hello": "Hi Asha, your code is 4471"})
        with self.assertLogs("crowkis", level="WARNING") as logs:
            session.decide("hello")
        self.assertFalse(any("4471" in line for line in logs.output))


if __name__ == "__main__":
    unittest.main()
