"""F7: the three rule gaps the F6 stress run found (follow-ups, "Yes, who is this?", action promises)."""

import unittest

from crowkis.rules.rule_set import RuleSet
from crowkis.understanding.word_rules.private_words import _ACTION_CLAIM
from crowkis.understanding.word_rules.follow_up import _is_context_dependent

FOLLOW_UPS = [
    "Do I need an ID proof for that?", "How many times do you try again after that?",
    "Compare it with the MacBook Air", "Done, what next?", "Yes, who is this?", "No, what is this about?",
]
STANDALONE = [
    "What are your opening hours?", "Is it refundable if I cancel within a week?",
    "What does it cost to send a parcel?", "What is the refund policy for this product?",
    "How do I return it?", "Do you ship to this country?", "What happens after that date passes?",
    "No refund policy applies to sale items?", "Yes, what are your opening hours?", "Yes, do you deliver on Sundays?",
]


class F7RuleGaps(unittest.TestCase):
    def test_follow_ups_are_context_dependent(self):
        for text in FOLLOW_UPS:
            self.assertTrue(_is_context_dependent(text), text)

    def test_general_questions_stay_shareable(self):
        for text in STANDALONE:
            self.assertFalse(_is_context_dependent(text), text)

    def test_action_promise_is_not_shared_on_voice(self):
        self.assertIn("VoiceActionClaim", RuleSet.voice().sharing.names)
        self.assertTrue(_ACTION_CLAIM.search("I will add milk and eggs to your shopping list."))
        self.assertTrue(_ACTION_CLAIM.search("Sure, I'll book that for you."))
        self.assertTrue(_ACTION_CLAIM.search("Sure, I’ll book that."))
        self.assertTrue(_ACTION_CLAIM.search("Milk and eggs have been added to your list."))
        self.assertFalse(_ACTION_CLAIM.search("You can add items to a list in the app."))
        self.assertFalse(_ACTION_CLAIM.search("We will be open until nine."))


if __name__ == "__main__":
    unittest.main()
