"""Any failure of the Voice add-on audio read is a miss, never the end of the turn, as the
basic read already was: not only a CrowkisError (a custom client, a timeout, a bug)."""
import asyncio
import unittest

import crowkis
from crowkis.voice_turns import AudioClips

from voice_turns_scenarios import AddonStore


class Clips(AudioClips):
    def __init__(self, session, rate):
        self._init_clips(session, rate)


class AudioReadErrorTests(unittest.TestCase):
    def test_any_error_from_the_addon_read_is_a_miss(self):
        class Broken(AddonStore):
            def caudioget(self, *args, **kwargs):
                raise TimeoutError("audio cache did not answer")

        session = crowkis.voice_session(client=Broken(), voice="v")
        clip = asyncio.run(Clips(session, 16000).get("Refunds take five business days."))
        self.assertIsNone(clip)
        self.assertEqual(session.agent.audio_errors, 1)

    def test_must_still_work_a_stored_clip_is_read(self):
        store = AddonStore()
        session = crowkis.voice_session(client=store, voice="v")
        clips = Clips(session, 16000)
        store.audio[("Hi.",) + clips._labels()] = b"\x01\x02"
        self.assertEqual(asyncio.run(clips.get("Hi.")), b"\x01\x02")


if __name__ == "__main__":
    unittest.main()
