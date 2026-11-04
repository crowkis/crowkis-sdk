"""v4 P1: the understanding slots hold today's word rules and no rewrite."""
import unittest

from crowkis.understanding.slots import NoRewrite, WordRuleClassifier
from crowkis.understanding.word_rules.follow_up import _is_context_dependent
from crowkis.understanding.word_rules.personal import _is_personal


class WordRuleClassifierTests(unittest.TestCase):
    def test_the_reading_is_the_word_rules(self):
        for text in ("my order 48213 has not arrived where is it", "and how long will that take",
                     "what is your refund policy", ""):
            with self.subTest(text=text):
                reading = WordRuleClassifier().classify(text)
                self.assertEqual(reading.is_personal, _is_personal(text))
                self.assertEqual(reading.is_context_dependent, _is_context_dependent(text))

    def test_no_rewrite_keeps_the_callers_words_as_the_key(self):
        reading = WordRuleClassifier().classify("what is your refund policy")
        self.assertIsNone(NoRewrite().rewrite("what is your refund policy", reading))


if __name__ == "__main__":
    unittest.main()
