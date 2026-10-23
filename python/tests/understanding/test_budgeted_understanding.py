"""v4 P4 step 4: BudgetedUnderstanding. A late or failed model means the word rules read the turn and it
keeps the caller's words; the turn is counted and logged without its words."""
import threading
import unittest

from crowkis import VoiceSession
from crowkis.agent import Agent
from crowkis.understanding.word_rule_classifier import WordRuleClassifier

from test_voice_stress_bugs import Store

BUDGET_MS = 50


class Slow:
    """A model that answers only after the test lets it (so a late answer never leaks into the next test)."""

    def __init__(self):
        self.release = threading.Event()

    def classify(self, text):
        self.release.wait(5)
        return type("Reading", (), {"is_personal": False, "is_context_dependent": False})()

    def rewrite(self, text, reading):
        return "what is the refund policy"


class Broken:
    def classify(self, text):
        raise RuntimeError("provider down")


class Rewords:
    def rewrite(self, text, reading):
        return "what is the refund policy"


def session_on(store, **options):
    return VoiceSession(Agent("caller", client=store), voice="v", **options)


class BudgetTests(unittest.TestCase):
    def test_a_late_model_leaves_the_turn_to_the_word_rules(self):
        store = Store()
        store.shared["what is the refund policy"] = "Refunds take five business days."
        slow = Slow()
        self.addCleanup(slow.release.set)
        session = session_on(store, classifier=slow, rewriter=slow, understand_budget_ms=BUDGET_MS)
        decision = session.decide("can you tell me about your refund policy")
        self.assertEqual(decision.action, "infer")  # not looked up under the model's late rewrite
        self.assertEqual(session.stats()["understand_timeouts"], 1)
        self.assertEqual(session.stats()["understand_errors"], 0)

    def test_a_failed_model_leaves_the_turn_to_the_word_rules_and_logs_no_words(self):
        session = session_on(Store(), classifier=Broken(), understand_budget_ms=BUDGET_MS)
        with self.assertLogs("crowkis", level="WARNING") as logs:
            decision = session.decide("my order 48213 has not arrived where is it")
        self.assertEqual(decision.rule, "OwnRecords")
        self.assertEqual(session.stats()["understand_errors"], 1)
        self.assertNotIn("48213", "\n".join(logs.output))
        self.assertIn("RuntimeError", "\n".join(logs.output))

    def test_a_model_in_time_reads_and_rewrites_the_turn(self):
        store = Store()
        store.shared["what is the refund policy"] = "Refunds take five business days."
        session = session_on(store, rewriter=Rewords(), understand_budget_ms=BUDGET_MS * 20)
        self.assertEqual(session.decide("can you tell me about your refund policy").action, "serve")
        self.assertEqual(session.stats()["understand_timeouts"], 0)

    def test_must_still_work_no_model_no_budget_no_new_counts(self):
        stats = session_on(Store(), understand_budget_ms=BUDGET_MS).stats()
        self.assertNotIn("understand_timeouts", stats)
        self.assertNotIn("understand_errors", stats)

    def test_must_still_work_no_budget_runs_the_model_as_it_is(self):
        session = session_on(Store(), rewriter=Rewords())
        self.assertIsInstance(session._classifier, WordRuleClassifier)
        self.assertNotIn("understand_timeouts", session.stats())

    def test_the_budget_must_be_positive(self):
        for budget in (0, -1):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                session_on(Store(), rewriter=Rewords(), understand_budget_ms=budget)


if __name__ == "__main__":
    unittest.main()
