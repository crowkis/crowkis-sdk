"""U1: the rewrite check and the stated-fact check are plain functions with the same answers as before."""

import unittest

from crowkis.understanding.model.checks import stated_fact_irrelevant, accepted_rewrite
from crowkis.understanding.model.frame import TurnFrame
from crowkis.understanding.slots import WordReading


def _frame(confidence=0.9, changes=False, fact="my car was hit", ftype="other"):
    return TurnFrame.from_dict({"kind": "general", "subject": "none", "confidence": confidence,
                                "fact_relevance": [{"fact": fact, "type": ftype, "changes_answer": changes}]})


class _Call:
    values = {}

    def __init__(self, stated=()):
        self._stated = list(stated)

    def stated(self):
        return self._stated

    def facts(self):
        return []

    def is_personal(self, text):
        return False

    def is_context_dependent(self, text):
        return False


class StatedFactIrrelevant(unittest.TestCase):
    def test_a_fact_the_model_is_sure_of_may_be_left_out(self):
        self.assertTrue(stated_fact_irrelevant("my car was hit", _frame()))

    def test_unsure_changing_or_high_risk_facts_count(self):
        self.assertFalse(stated_fact_irrelevant("my car was hit", _frame(confidence=0.3)))
        self.assertFalse(stated_fact_irrelevant("my car was hit", _frame(changes=True)))
        self.assertFalse(stated_fact_irrelevant("my car was hit", None))
        self.assertFalse(stated_fact_irrelevant("I am allergic to peanuts", _frame(fact="I am allergic to peanuts")))

    def test_each_clause_needs_its_own_entry(self):
        self.assertFalse(stated_fact_irrelevant("my car was hit and my husband has a heart condition", _frame()))


class AcceptedRewrite(unittest.TestCase):
    def test_a_safe_rewrite_keys_the_turn(self):
        text = "how do i reset a password"
        self.assertEqual(accepted_rewrite(text, WordReading(text), " How do I reset a password? ", _Call()),
                         "How do I reset a password?")

    def test_unsafe_rewrites_keep_the_callers_words(self):
        text = "how do i reset a password"
        self.assertIsNone(accepted_rewrite(text, WordReading(text), "", _Call()))
        self.assertIsNone(accepted_rewrite(text, WordReading(text), None, _Call()))
        self.assertIsNone(accepted_rewrite(text, WordReading(text), "How does Priya reset a password?", _Call()))
        self.assertIsNone(accepted_rewrite(text, WordReading(text), "How do I reset password 4821?", _Call()))
        self.assertIsNone(accepted_rewrite(text, WordReading(text), "How do I reset a password?", _Call(["I'm 70"])))


if __name__ == "__main__":
    unittest.main()
