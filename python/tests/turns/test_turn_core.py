"""v4 P2: TurnCore runs the steps it is given (rules, pairing, lookup are injected)."""
import unittest

from crowkis.rules import RuleSet
from crowkis.turns.turn_core import TurnCore

from test_voice_stress_bugs import Store, session_on


def core_without(session, names):
    return TurnCore(session, rules=RuleSet.voice().without(names), call=session._call, pairing=session._pairing,
                    cache_lookup=session._cache_lookup, classifier=session._classifier, rewriter=session._rewriter)


class TurnCoreTests(unittest.TestCase):
    def test_the_rules_it_is_given_decide_the_turn(self):
        session = session_on(Store())
        self.assertEqual(session.decide("do you deliver on").rule, "CutOff")
        decision = core_without(session_on(Store()), ["CutOff"]).decide("do you deliver on")
        self.assertEqual(decision.rule, "ConfidenceBar")

    def test_record_pairs_the_answer_with_its_turn(self):
        store = Store()
        session = session_on(store)
        core = core_without(session, [])
        session._pairing.offer(session._pairing.begin(), True)
        outcome = core.record("what is your refund policy", "Refunds take five days.", turn=None, private=False,
                              instructions=None)
        self.assertEqual(outcome, "saved")
        self.assertEqual(store.writes, [("what is your refund policy", "Refunds take five days.", False)])


if __name__ == "__main__":
    unittest.main()
