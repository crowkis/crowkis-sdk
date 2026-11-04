"""v4 P4 step 5: voice_session(channel=...) takes the budgets it is not given from the channel's profile."""
import unittest

from crowkis import CrowkisClient, voice_session
from crowkis.turns.values import REALTIME, VOICE, Channel


def factory(**options):
    return voice_session(client=CrowkisClient(port=1), **options)


class ChannelProfileTests(unittest.TestCase):
    def test_must_still_work_a_voice_call_by_default(self):
        session = factory()
        self.assertIs(session.channel, VOICE)
        self.assertIs(session._call.channel, VOICE)
        self.assertEqual(session.latency_budget_ms, 250)

    def test_a_channel_by_name_or_profile(self):
        self.assertIs(factory(channel="realtime").channel, REALTIME)
        self.assertIs(factory(channel=REALTIME).channel, REALTIME)
        self.assertIs(Channel.of(" Voice "), VOICE)

    def test_the_budgets_come_from_the_channel_unless_given(self):
        custom = Channel("slow-line", isolates_context=True, budget_ms=400, audio=True, spoken=True,
                         saves_answers=True, understand_budget_ms=600)
        self.assertEqual(factory(channel=custom).latency_budget_ms, 400)
        self.assertEqual(factory(channel=custom, latency_budget_ms=100).latency_budget_ms, 100)

    def test_must_still_work_none_turns_the_budget_off(self):
        self.assertIsNone(factory(latency_budget_ms=None).latency_budget_ms)

    def test_an_unknown_channel_is_an_error(self):
        with self.assertRaises(ValueError):
            factory(channel="fax")


if __name__ == "__main__":
    unittest.main()
