"""Server-free tests for the rule checker and key builder (turn understanding v2.2, part 2).

Run:  python -m pytest tests/ -q
"""

import unittest

from crowkis.callstate import CallState
from crowkis.turn import TurnFrame
from crowkis.verify import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT, RuleChecker


def frame(**kw):
    base = {"kind": "general", "subject": "none", "confidence": 0.9, "question_type": "policy",
            "entities": [], "attributes": {}}
    base.update(kw)
    return TurnFrame.from_dict(base)


def check(turn, state=None, checker=None, **kw):
    return (checker or RuleChecker()).check(frame(**kw), turn, state or CallState())


class SharingTests(unittest.TestCase):
    def test_a_clean_general_question_is_shared(self):
        v = check("How long does shipping take?", question="How long does shipping take?")
        self.assertTrue(v.shared)
        self.assertEqual(v.route, SHARED)
        self.assertEqual(v.key, "[kb=1] How long does shipping take?")

    def test_a_name_said_with_the_question_never_reaches_the_key(self):
        v = check("What time is check-in? Sarah here.", question="What time is check-in?",
                  entities=[{"text": "Sarah", "type": "person_name"}])
        self.assertTrue(v.shared)
        self.assertNotIn("Sarah", v.key)

    def test_a_name_left_in_the_question_blocks_sharing(self):
        v = check("Sarah here. What time is check-in?", question="What time is check-in for Sarah?",
                  entities=[{"text": "Sarah", "type": "person_name"}])
        self.assertFalse(v.shared)
        self.assertIn("V5_identifying", v.reasons)

    def test_saturday_and_prices_are_not_blocked(self):
        self.assertTrue(check("What are your branch hours on Saturday?",
                              question="What are your branch hours on Saturday?").shared)
        self.assertTrue(check("Is shipping free on orders over 10000 rupees?",
                              question="Is shipping free on orders over 10000 rupees?").shared)

    def test_an_order_number_or_email_in_the_key_blocks_sharing(self):
        for turn in ("Where is order 55512?", "Can I change john@mail.com?", "Call me on 9876543210?"):
            v = check(turn, question=turn)
            self.assertFalse(v.shared, turn)
            self.assertIn("V5_identifying", v.reasons, turn)

    def test_words_not_in_the_turn_or_state_block_sharing(self):
        v = check("And for ten people?", question="What does the Max plan cost for 10 people?")
        self.assertFalse(v.shared)
        self.assertTrue(any(r.startswith("V6_ungrounded") for r in v.reasons))

    def test_a_follow_up_grounded_in_the_call_state_is_shared(self):
        state = CallState(active_question="What does the Pro plan cost?")
        v = check("And for ten people?", state, question="What does the Pro plan cost for 10 people?", uses_state=True)
        self.assertTrue(v.shared)

    def test_words_named_by_the_agent_count_as_grounded(self):
        state = CallState()
        state.note_agent_reply("That would be the Golden Gate Hotel.", mentions=["Golden Gate Hotel"])
        v = check("Where is that in San Francisco?", state, question="Where is the Golden Gate Hotel?",
                  question_type="place_fact", uses_state=True)
        self.assertTrue(v.shared)

    def test_word_forms_and_request_verbs_do_not_block(self):
        self.assertTrue(check("I would like to know when promo code expires",
                              question="When does a promo code expire?").shared)
        self.assertTrue(check("I wanna know more about these Guess jeans for 59 dollars.",
                              question="What can you tell me about Guess jeans for 59 dollars?").shared)

    def test_a_dropped_detail_blocks_sharing(self):
        v = check("How do I return a damaged phone case?", question="How do I return an item?",
                  entities=[{"text": "damaged", "type": "condition", "answer_relevant": True}])
        self.assertFalse(v.shared)
        self.assertTrue(any(r.startswith("V7_lost") for r in v.reasons))


class NotSharedTests(unittest.TestCase):
    def test_urgent_goes_first(self):
        v = check("I smell gas in my kitchen.", kind="sensitive", subject="self", urgent=True)
        self.assertEqual((v.shared, v.route), (False, URGENT))

    def test_low_confidence_or_abstain_is_not_shared(self):
        self.assertFalse(check("x", question="What are your hours?", confidence=0.4).shared)
        self.assertFalse(check("x", question="What are your hours?", abstain=True).shared)

    def test_the_confidence_floor_is_per_business(self):
        lenient = RuleChecker(confidence_floor=0.4)
        self.assertTrue(check("What are your hours?", checker=lenient, question="What are your hours?",
                              confidence=0.5).shared)

    def test_personal_live_and_action_turns_route_to_the_right_place(self):
        self.assertEqual(check("Where is my order?", kind="personal", subject="self").route, PERSONAL)
        self.assertEqual(check("Is it in stock?", kind="live").route, TOOLS)
        self.assertEqual(check("Cancel my order.", kind="action", subject="self").route, TOOLS)
        self.assertEqual(check("Thanks!", kind="chitchat").route, AGENT)

    def test_an_own_purchase_contradicts_general(self):
        v = check("Can I return the shoes I bought?", question="Can I return shoes?",
                  entities=[{"text": "the shoes I bought", "type": "own_purchase"}])
        self.assertFalse(v.shared)
        self.assertIn("V4_about_someone", v.reasons)

    def test_a_task_step_is_never_shared(self):
        v = check("I don't want to spend more than $100 for two.", task_step=True,
                  question="Which Italian restaurants cost no more than $100 for two?")
        self.assertEqual((v.shared, v.route), (False, TASK))

    def test_answering_the_agent_during_a_task_is_a_task_step(self):
        state = CallState()
        state.note_agent_reply("What is your budget?", task="booking")
        v = check("Under 100 dollars for two.", state, question="Which restaurants cost under 100 dollars for two?")
        self.assertEqual(v.route, TASK)

    def test_answering_the_agent_with_no_task_running_is_judged_normally(self):
        state = CallState()
        state.note_agent_reply("What would you like to know?")
        v = check("Your return policy please.", state, question="What is your return policy?")
        self.assertTrue(v.shared)


class KeyTests(unittest.TestCase):
    def test_a_tier_enters_the_key_only_when_it_changes_the_answer(self):
        changes = check("I'm premium, how long does shipping take?", question="How long does shipping take?",
                        attributes={"segment": {"value": "premium", "changes_answer": True}})
        no_change = check("I'm premium, do you have parking?", question="Do you have parking?",
                          attributes={"segment": {"value": "premium", "changes_answer": False}})
        self.assertIn("segment=premium", changes.key)
        self.assertNotIn("segment", no_change.key)

    def test_a_place_question_carries_the_calls_location(self):
        state = CallState()
        state.apply(frame(kind="dialogue", task_step=False, question="-",
                          attributes={"region": {"value": "laguna beach", "changes_answer": True}},
                          entities=[{"text": "Laguna Beach", "type": "place"}]), shared=False)
        state.note_agent_reply("I found The Press Bistro.", mentions=["The Press Bistro"])
        v = check("Do they have steak there?", state, question="Does The Press Bistro have steak?",
                  question_type="place_fact", uses_state=True)
        self.assertTrue(v.shared)
        self.assertIn("region=laguna beach", v.key)

    def test_expiry_follows_the_question_type(self):
        self.assertIsNone(check("refund policy?", question="What is your refund policy?").ttl)
        state = CallState()
        self.assertEqual(check("hotels in Pune", state, question="What hotels are in Pune?",
                               question_type="search").ttl, 3600)

    def test_a_new_knowledge_version_changes_every_key(self):
        turn = "What is your refund policy?"
        v1 = check(turn, question=turn, checker=RuleChecker(knowledge_version="1"))
        v2 = check(turn, question=turn, checker=RuleChecker(knowledge_version="2"))
        self.assertTrue(v1.shared and v2.shared)
        self.assertNotEqual(v1.key, v2.key)


if __name__ == "__main__":
    unittest.main()
