"""v4 P4 review fixes: a plugged-in model never makes a call less private. A rewrite is used only for a
turn that is neither personal nor a follow-up (by its reading or the word rules), only when it adds no
caller detail, and only for the turn it was made for; a failing model never ends a call."""
import threading
import time
import unittest

from crowkis.understanding.word_rule_classifier import WordRuleClassifier

from test_voice_stress_bugs import Store, session_on


class Reads:
    """A reading the test sets (general and stand-alone unless told otherwise)."""

    def __init__(self, personal=False, follow_up=False):
        self.is_personal = personal
        self.is_context_dependent = follow_up


class General:
    def classify(self, text):
        return Reads()


class Script:
    """A rewriter that answers from a list, one rewrite per turn (None: no rewrite)."""

    def __init__(self, *rewrites):
        self._rewrites = list(rewrites)

    def rewrite(self, text, reading):
        return self._rewrites.pop(0)


class Broken:
    def classify(self, text):
        raise RuntimeError("provider down")


class RewriteSafetyTests(unittest.TestCase):
    def test_a_repeated_turn_without_a_rewrite_is_saved_under_its_own_words(self):
        store = Store()
        session = session_on(store, rewriter=Script("what is the price of the gold plan", None))
        session.record(session.decide("what does the plan cost"), "The gold plan costs 499.")
        session.record(session.decide("what does the plan cost"), "The silver plan costs 199.")
        self.assertNotEqual(store.shared.get("what is the price of the gold plan"), "The silver plan costs 199.")

    def test_a_word_rule_follow_up_stays_a_follow_up_whatever_the_reading(self):
        class FlightPersonal:
            def classify(self, text):
                return Reads(personal="flight" in text)

        session = session_on(Store(), classifier=FlightPersonal())
        session.record(session.decide("when does the next flight to delhi leave"), "Your flight leaves at 6 pm.")
        decision = session.decide("and how long will that take")
        self.assertEqual(decision.rule, "PrivateChain")
        self.assertFalse(decision.cacheable)

    def test_a_follow_up_is_never_saved_under_a_bare_rewrite(self):
        store = Store()
        session = session_on(store, classifier=General(), rewriter=Script(None, "what are the opening hours"))
        session.record(session.decide("tell me about the paris office"), "The Paris office is on Rue Royale.")
        session.record(session.decide("and what are its hours"), "The Paris office opens 9 to 5.")
        self.assertNotIn("what are the opening hours", store.shared)

    def test_a_turn_the_word_rules_call_personal_is_never_rewritten(self):
        store = Store()
        session = session_on(store, classifier=General(), rewriter=Script("what is the refund policy"),
                             values={"order": "48213"}, share_templates=True)
        session.record(session.decide("where is my order 48213"), "Your order 48213 ships tomorrow.")
        self.assertNotIn("what is the refund policy", store.reads)
        self.assertNotIn("what is the refund policy", store.templates)

    def test_a_rewrite_that_adds_a_detail_the_caller_did_not_say_is_dropped(self):
        for rewrite in ("what are the hours for John Smith on sunday", "what are the hours at 12 elm street",
                        "what are the hours for order 48213"):
            with self.subTest(rewrite=rewrite):
                store = Store()
                session = session_on(store, classifier=General(), rewriter=Script(rewrite))
                session.record(session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.")
                self.assertNotIn(rewrite, store.reads)
                self.assertNotIn(rewrite, store.shared)

    def test_a_rewrite_that_carries_a_declared_value_is_dropped(self):
        store = Store()
        session = session_on(store, classifier=General(), rewriter=Script("what are the hours for priya"),
                             values={"name": "Priya"})
        session.decide("what are your opening hours on sunday")
        self.assertNotIn("what are the hours for priya", store.reads)

    def test_a_blank_rewrite_is_no_rewrite(self):
        store = Store()
        session = session_on(store, classifier=General(), rewriter=Script("  "))
        session.record(session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.")
        self.assertIn("what are your opening hours on sunday", store.shared)

    def test_must_still_work_a_safe_rewrite_is_used(self):
        store = Store()
        session = session_on(store, classifier=General(), rewriter=Script("what are the opening hours on sunday"))
        session.record(session.decide("when do you open on sundays"), "We open at 10 on Sundays.")
        self.assertEqual(store.shared.get("what are the opening hours on sunday"), "We open at 10 on Sundays.")

    def test_a_failing_model_without_a_budget_never_ends_the_call(self):
        session = session_on(Store(), classifier=Broken())
        with self.assertLogs("crowkis", level="WARNING"):
            decision = session.decide("what are your opening hours on sunday")
        self.assertEqual(decision.action, "infer")
        self.assertEqual(session.stats()["understand_errors"], 1)


class HungModelTests(unittest.TestCase):
    def test_a_hung_model_holds_only_a_few_workers(self):
        from crowkis.understanding.budgeted_understanding import MAX_IN_FLIGHT

        release = threading.Event()
        calls = []

        class Hung:
            def classify(self, text):
                calls.append(text)
                release.wait(5)
                return WordRuleClassifier().classify(text)

        self.addCleanup(release.set)
        session = session_on(Store(), classifier=Hung(), understand_budget_ms=20)
        for _ in range(MAX_IN_FLIGHT + 3):
            session.decide("what are your opening hours on sunday")
        time.sleep(0.05)
        self.assertEqual(len(calls), MAX_IN_FLIGHT)
        self.assertEqual(session.stats()["understand_timeouts"], MAX_IN_FLIGHT + 3)


if __name__ == "__main__":
    unittest.main()
