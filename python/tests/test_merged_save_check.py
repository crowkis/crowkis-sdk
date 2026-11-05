"""v4 P5 item 3: the merged save check. Voice with an understander gains PrivateWord and ActionClaim."""
import unittest

from crowkis.understanding.slots import WordRuleClassifier

from test_voice_stress_bugs import Store, session_on


class VoiceMergedSaveTests(unittest.TestCase):
    def test_a_word_from_a_private_turn_is_never_shared(self):
        store = Store()
        session = session_on(store, classifier=WordRuleClassifier())
        session.record(session.decide("my order 48213 for Sarah Khan has not arrived"), "I will check order 48213.")
        decision = session.decide("what is your refund policy")
        session.record(decision, "Sarah, refunds take five business days.")
        self.assertEqual(decision.save_rule, "VoicePrivateWord")
        self.assertEqual(store.shared, {})

    def test_an_answer_saying_it_was_done_is_never_shared(self):
        store = Store()
        session = session_on(store, classifier=WordRuleClassifier())
        decision = session.decide("what is your refund policy")
        session.record(decision, "I have cancelled your order and refunded you.")
        self.assertEqual(decision.save_rule, "VoiceActionClaim")
        self.assertEqual(store.shared, {})

    def test_f7_the_default_voice_rules_also_keep_an_action_claim_private(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        session.record(decision, "I have cancelled your order and refunded you.")
        self.assertEqual(decision.save_rule, "VoiceActionClaim")
        self.assertEqual(store.shared, {})


if __name__ == "__main__":
    unittest.main()
