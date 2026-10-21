"""A question must never be served the answer to a different question (Phase 5, N2).

The server matches on meaning, and two questions that differ in what they ask about
can score above the serve bar: "How late does the rooftop orchid greenhouse stay open
on Sundays?" was served "The riverside greenhouse opens at nine on Sunday mornings."
When a shareable answer is saved, the session also keeps which question it answers
(a small record in the tool cache, keyed by the answer). On a hit that is not an exact
match, a stored question with specific words the asked one does not have, while the
asked one has its own, is a different question: the model answers instead."""
import unittest

import crowkis
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice import _different_specifics

from conformance import ConformanceStore

RIVERSIDE = "What time does the riverside greenhouse open on Sunday mornings?"
RIVERSIDE_ANSWER = "The riverside greenhouse opens at nine on Sunday mornings."


def _ask(store, question, reply="From the model."):
    session = crowkis.voice_session(client=store)
    calls = []
    decision = session.answer(question, lambda m: calls.append(m) or reply)
    _wait_for_audio_stores()
    return decision, calls, session


class DifferentQuestionTests(unittest.TestCase):
    def setUp(self):
        _wait_for_audio_stores()  # no other test's background work still queued

    def _learned(self, aliases, question=RIVERSIDE, answer=RIVERSIDE_ANSWER):
        store = ConformanceStore(aliases=aliases)
        decision, calls, _ = _ask(store, question, answer)
        self.assertEqual((decision.action, decision.stored), ("infer", True))
        return store

    def test_a_question_about_something_else_is_not_served_the_stored_answer(self):
        for asked in ("How late does the rooftop orchid greenhouse stay open on Sundays?",
                      "What time does the riverside greenhouse open on Saturday mornings?",
                      "What time does the city museum open on Sunday mornings?"):
            with self.subTest(asked=asked):
                store = self._learned({asked: RIVERSIDE})
                decision, calls, session = _ask(store, asked)
                self.assertEqual(decision.action, "infer", decision.reason)
                self.assertIn("different question", decision.reason)
                self.assertEqual(len(calls), 1, "the model answers instead")
                self.assertEqual(session.stats()["different_question"], 1)

    def test_must_still_work_a_rewording_is_served(self):
        for stored, asked in (("how do I turn on dark mode", "how can I turn on dark mode"),
                              ("what are your opening hours", "when are you open"),
                              ("how do I reset my password", "how can I reset my password please")):
            with self.subTest(asked=asked):
                store = self._learned({asked: stored}, stored, "Here is how.")
                decision, calls, _ = _ask(store, asked)
                self.assertEqual(decision.action, "serve", decision.reason)
                self.assertEqual(calls, [])

    def test_must_still_work_the_same_question_is_served(self):
        store = self._learned({})
        decision, calls, _ = _ask(store, RIVERSIDE)
        self.assertEqual((decision.action, calls), ("serve", []))

    def test_an_answer_saved_without_its_question_is_served_as_before(self):
        # Saved by an older SDK, or by hand: nothing to compare with, so nothing changes.
        asked = "How late does the rooftop orchid greenhouse stay open on Sundays?"
        store = ConformanceStore(aliases={asked: RIVERSIDE}, seed={RIVERSIDE: RIVERSIDE_ANSWER})
        decision, calls, _ = _ask(store, asked)
        self.assertEqual(decision.action, "serve")

    def test_a_record_that_cannot_be_read_or_written_never_breaks_a_turn(self):
        class Broken(ConformanceStore):
            def get(self, *a, **k):
                raise RuntimeError("refused")

            def set(self, *a, **k):
                raise RuntimeError("refused")

        asked = "How late does the rooftop orchid greenhouse stay open on Sundays?"
        store = Broken(aliases={asked: RIVERSIDE})
        first, _, _ = _ask(store, RIVERSIDE, RIVERSIDE_ANSWER)
        self.assertTrue(first.stored)
        decision, _, _ = _ask(store, asked)
        self.assertEqual(decision.action, "serve", "unknown means as before")

    def test_the_rule_itself(self):
        self.assertTrue(_different_specifics("hours on saturday", "hours on sunday"))
        self.assertFalse(_different_specifics("how can i turn on dark mode", "how do i turn on dark mode"))
        self.assertFalse(_different_specifics("when are you open", "what are your opening hours"))
        self.assertFalse(_different_specifics("", ""))
        self.assertFalse(_different_specifics("कब खुलता है", "कब खुलता है"))


if __name__ == "__main__":
    unittest.main()
