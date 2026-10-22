"""v4 P2 cleanup: Stats keeps the session's counters; each public counter attribute reads and writes it."""
import unittest

from crowkis.runtime.stats import Counter, Stats

from test_voice_stress_bugs import Store, session_on


class StatsTests(unittest.TestCase):
    def test_counters_start_at_zero_and_add_by_name_or_member(self):
        stats = Stats()
        stats.add(Counter.FILLED)
        stats.add("filled")
        self.assertEqual(stats.get(Counter.FILLED), 2)
        stats.count_rule("CutOff")
        self.assertEqual(stats.rule_counts(), {"CutOff": 1})

    def test_the_session_counters_are_the_stats(self):
        session = session_on(Store())
        session.barge_ins += 1
        self.assertEqual(session._stats.get(Counter.BARGE_INS), 1)
        session.decide("do you deliver on")
        self.assertEqual((session.refused_short, session.stats()["rules"]), (1, {"CutOff": 1}))


if __name__ == "__main__":
    unittest.main()
