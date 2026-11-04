"""v4 P2: TurnCore runs the steps it is given (rules, pairing, lookup are injected)."""
import unittest

from crowkis.rules import RuleSet
from crowkis.turns.results import VoiceAnswered

from test_voice_stress_bugs import Store, session_on


def core_without(session, names):
    return session._build_core(RuleSet.voice().without(names))


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
        outcome = core.record(VoiceAnswered("what is your refund policy", "Refunds take five days.", turn=None,
                                            private=False, instructions=None))
        self.assertEqual(outcome, "saved")
        self.assertEqual(store.writes, [("what is your refund policy", "Refunds take five days.", False)])

    def test_a_tool_built_answer_is_never_shared_even_with_tool_result_off(self):
        # v4 P5.5 parity: an answer is cacheable only when decide() offered it AND it is not private,
        # so with ToolResult turned off the NotShareable rule still keeps a tool-built answer in the call.
        store = Store()
        session = session_on(store)
        core = core_without(session, ["ToolResult"])
        session._pairing.offer(session._pairing.begin(), True)
        outcome = core.record(VoiceAnswered("what is your refund policy", "Refunds take five days.", turn=None,
                                            private=True, instructions=None))
        self.assertEqual(outcome, "kept")
        self.assertEqual(outcome.rule, "NotShareable")
        self.assertEqual(store.writes, [])


if __name__ == "__main__":
    unittest.main()
