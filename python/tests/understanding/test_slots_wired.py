"""v4 P4 step 2: a session uses the classifier and rewriter it is given (defaults: the word rules, no rewrite)."""
import unittest

from crowkis import CrowkisClient, voice_session
from crowkis.understanding.slots import BudgetedUnderstanding, WordRuleClassifier

from test_voice_stress_bugs import Store, session_on


class AlwaysPersonal:
    def classify(self, text, facts=()):
        return type("Reading", (), {"is_personal": True, "is_context_dependent": False})()


class ReadsPersonal:
    """The word rules, except that one turn is read as personal."""

    def __init__(self, personal_turn):
        self._personal_turn = personal_turn

    def classify(self, text, facts=()):
        reading = WordRuleClassifier().classify(text)
        if text != self._personal_turn:
            return reading
        return type("Reading", (), {"is_personal": True, "is_context_dependent": reading.is_context_dependent})()


class Rewords:
    def rewrite(self, text, reading):
        return "what is the refund policy"


class SlotTests(unittest.TestCase):
    def test_a_plugged_in_classifier_reads_the_turn(self):
        decision = session_on(Store(), classifier=AlwaysPersonal()).decide("what is your refund policy")
        self.assertEqual(decision.rule, "OwnRecords")

    def test_a_plugged_in_rewriter_keys_the_lookup(self):
        store = Store()
        store.shared["what is the refund policy"] = "Refunds take five business days."
        decision = session_on(store, rewriter=Rewords()).decide("whats ur refund policy pls")
        self.assertEqual(decision.action, "serve")

    def test_the_factory_passes_them_through(self):
        classifier, rewriter = AlwaysPersonal(), Rewords()
        session = voice_session(client=CrowkisClient(port=1), classifier=classifier, rewriter=rewriter)
        # The factory gives a plugged-in model the understanding budget (P4 step 4).
        self.assertIsInstance(session._classifier, BudgetedUnderstanding)
        self.assertIs(session._rewriter, session._classifier)
        self.assertIs(session._classifier._classifier, classifier)
        self.assertIs(session._classifier._rewriter, rewriter)

    def test_a_turn_the_classifier_reads_personal_is_never_shared(self):
        store = Store()
        session = session_on(store, classifier=AlwaysPersonal())
        decision = session.decide("what is your refund policy")
        self.assertIsNone(decision.messages)
        self.assertFalse(decision.cacheable)
        session.record(decision, "Refunds take five business days.")
        self.assertNotIn("what is your refund policy", store.shared)

    def test_a_follow_up_to_a_turn_the_classifier_read_personal_is_private(self):
        session = session_on(Store(), classifier=ReadsPersonal("what does the gold plan cost"))
        session.record(session.decide("what does the gold plan cost"), "The gold plan costs 499 a month.")
        decision = session.decide("and how long will that take")
        self.assertEqual(decision.rule, "PrivateChain")
        self.assertFalse(decision.cacheable)

    def test_must_still_work_a_follow_up_to_a_general_turn_is_shared(self):
        session = session_on(Store(), classifier=ReadsPersonal("something else entirely"))
        session.record(session.decide("what does the gold plan cost"), "The gold plan costs 499 a month.")
        self.assertTrue(session.decide("and how long will that take").cacheable)

    def test_must_still_work_the_defaults_are_the_word_rules(self):
        self.assertEqual(session_on(Store()).decide("what is your refund policy").rule, "ConfidenceBar")


if __name__ == "__main__":
    unittest.main()
