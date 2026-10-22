"""v4 P1: RuleChain and RuleSet (first objection wins, the floor lock, the voice defaults)."""
import unittest

from crowkis import CrowkisError
from crowkis.rules import FloorRuleLocked, RuleChain, RuleSet, UnknownRule
from crowkis.turns import Verdict


class Objects:
    def __init__(self, name, objects, floor=False):
        self.name, self.objects, self.floor, self.seen = name, objects, floor, 0

    def check(self, subject):
        self.seen += 1
        return Verdict(self.name, f"{self.name} objects") if self.objects else None


class RuleChainTests(unittest.TestCase):
    def test_the_first_objection_wins_and_later_rules_do_not_run(self):
        later = Objects("Later", True)
        chain = RuleChain([Objects("Quiet", False), Objects("First", True), later])
        self.assertEqual(chain.first_objection("turn").rule, "First")
        self.assertEqual(later.seen, 0)

    def test_no_objection_lets_the_subject_through(self):
        self.assertIsNone(RuleChain([Objects("Quiet", False)]).first_objection("turn"))
        self.assertIsNone(RuleChain([]).first_objection("turn"))

    def test_a_policy_rule_can_be_turned_off(self):
        chain = RuleChain([Objects("Policy", True), Objects("Other", False)]).without(["Policy"])
        self.assertEqual(chain.names, ("Other",))
        self.assertIsNone(chain.first_objection("turn"))

    def test_a_floor_rule_stays_on_without_the_unsafe_flag(self):
        chain = RuleChain([Objects("Floor", True, floor=True)])
        with self.assertRaises(FloorRuleLocked) as caught:
            chain.without(["Floor"])
        self.assertIsInstance(caught.exception, CrowkisError)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(chain.without(["Floor"], unsafe=True).names, ())


class VoiceRuleSetTests(unittest.TestCase):
    def test_the_voice_defaults_are_todays_rules_in_todays_order(self):
        rules = RuleSet.voice()
        self.assertEqual(rules.before_filler.names, ("EmptyTurn",))
        self.assertEqual(rules.question.names, ("CallContextTaint", "TooShort", "CutOff", "OwnRecords",
                                                "FollowUpWithoutContext", "PrivateChain"))
        self.assertEqual(rules.hit.names, ("ConfidenceBar", "TemplateSlotMissing", "PiiPlaceholder",
                                           "DifferentQuestion", "ShortTurnUnvouched", "CommitmentRewording",
                                           "ScreenOnlyAnswer"))
        self.assertEqual(rules.answer_given.names, ("EmptyAnswer",))
        self.assertEqual(rules.before_sharing.names, ("NoKey", "ToolResult", "PromptCallerDetails"))
        self.assertEqual(rules.personal.name, "PersonalTemplate")
        self.assertEqual(rules.sharing.names, ("TaintedCall", "NotShareable", "DeclaredValue", "CallerIdentifier",
                                               "NonAnswer"))

    def test_rule_names_are_a_list_never_one_string(self):
        with self.assertRaises(TypeError):
            RuleChain([Objects("PrivateChain", True)]).without("PrivateChainX")
        with self.assertRaises(TypeError):
            RuleSet.voice().without("PrivateChainX")

    def test_an_unknown_rule_name_is_refused(self):
        with self.assertRaises(UnknownRule) as caught:
            RuleSet.voice().without(["PrivateChainX"])
        self.assertIsInstance(caught.exception, ValueError)

    def test_the_personal_answer_rule_cannot_be_turned_off(self):
        for unsafe in (False, True):
            with self.subTest(unsafe=unsafe), self.assertRaises(FloorRuleLocked):
                RuleSet.voice().without(["PersonalTemplate"], unsafe=unsafe)

    def test_the_floor_rules_of_the_voice_defaults_are_locked(self):
        rules = RuleSet.voice()
        for floor_rule in ("OwnRecords", "PromptCallerDetails"):
            with self.subTest(rule=floor_rule), self.assertRaises(FloorRuleLocked):
                rules.without([floor_rule])
        self.assertNotIn("CutOff", rules.without(["CutOff"]).question.names)


if __name__ == "__main__":
    unittest.main()
