"""v4 P4 step 2: a session uses the classifier and rewriter it is given (defaults: the word rules, no rewrite)."""
import unittest

from crowkis import CrowkisClient, voice_session

from test_voice_stress_bugs import Store, session_on


class AlwaysPersonal:
    def classify(self, text):
        return type("Reading", (), {"is_personal": True, "is_context_dependent": False})()


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
        self.assertIs(session._classifier, classifier)
        self.assertIs(session._rewriter, rewriter)

    def test_must_still_work_the_defaults_are_the_word_rules(self):
        self.assertEqual(session_on(Store()).decide("what is your refund policy").rule, "ConfidenceBar")


if __name__ == "__main__":
    unittest.main()
