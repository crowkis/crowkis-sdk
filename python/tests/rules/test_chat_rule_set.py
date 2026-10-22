"""v4 P3: Chat's V1-V10 as a rule set (order, the V7 group, the floor lock, a live confidence floor)."""
import unittest

from crowkis.callstate import CallState
from crowkis.rules import FloorRuleLocked
from crowkis.rules.chat_rule_set import ChatRuleSet
from crowkis.turn import TurnFrame
from crowkis.verify import RuleChecker

QUESTION = {"kind": "general", "subject": "none", "confidence": 0.5, "question": "What is your refund policy?"}


class ChatRuleSetTests(unittest.TestCase):
    def test_chats_rules_are_todays_in_todays_order(self):
        rules = ChatRuleSet.chat(0.6)
        self.assertEqual(rules.decisive.names, ("UrgentTurn", "TaskStep"))
        self.assertEqual(rules.frame.names, ("UncertainFrame", "NotGeneral", "AboutSomeone", "NoQuestion"))
        self.assertEqual(rules.question.all_names, ("IdentifyingDetails", "Ungrounded", "UnresolvedReference",
                                                    "V7_LostOrDropped", "LostDetail", "StatedFacts"))

    def test_a_rule_inside_the_v7_group_can_be_turned_off(self):
        rules = ChatRuleSet.chat(0.6).without(["StatedFacts"])
        self.assertNotIn("StatedFacts", rules.question.all_names)
        self.assertIn("LostDetail", rules.question.all_names)

    def test_chats_floor_rules_are_locked(self):
        for floor_rule in ("UrgentTurn", "AboutSomeone", "IdentifyingDetails"):
            with self.subTest(rule=floor_rule), self.assertRaises(FloorRuleLocked):
                ChatRuleSet.chat(0.6).without([floor_rule])

    def test_must_still_work_a_confidence_floor_changed_later_is_read(self):
        checker = RuleChecker()
        frame = TurnFrame.from_dict(QUESTION)
        self.assertEqual(checker.check(frame, "what is your refund policy", CallState()).reasons, ["V2_uncertain"])
        checker.confidence_floor = 0.4
        self.assertTrue(checker.check(frame, "what is your refund policy", CallState()).shared)


if __name__ == "__main__":
    unittest.main()
