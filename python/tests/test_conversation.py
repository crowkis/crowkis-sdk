"""Server-free tests for crowkis.Conversation, the cache decisions every channel shares.

A chat backend and a voice agent both drive a Conversation; these tests pin the
decisions themselves, with no client and no I/O. Run:  python -m pytest tests/ -q
"""

import unittest

from crowkis import Conversation, Saving, TurnPlan
from crowkis.conversation import (
    FILLER, INTERRUPTED, KEPT, LOOKUP, MODEL, NON_ANSWER, NOT_SAVED, PRIVATE, SAVED, TEMPLATE,
)


def turn(conv: Conversation, said: str, answer: str) -> Saving:
    """One model turn: plan it, answer it, settle it."""
    return conv.settle(conv.plan(said), answer)


class PlanTests(unittest.TestCase):
    def test_a_general_question_is_looked_up_and_the_model_reads_it_alone(self):
        plan = Conversation().plan("How long does shipping take?")
        self.assertEqual(plan.action, LOOKUP)
        self.assertEqual(plan.key, "How long does shipping take?")
        self.assertEqual(plan.messages, [{"role": "user", "content": "How long does shipping take?"}])
        self.assertTrue(plan.shareable)
        self.assertFalse(plan.personal)
        self.assertIsNone(plan.threshold)
        self.assertEqual(plan.model_sees, "question")

    def test_a_follow_up_is_keyed_and_read_with_the_question_before_it(self):
        conv = Conversation()
        turn(conv, "What is your return policy?", "You can return items within 30 days.")
        plan = conv.plan("How long does it take?")
        self.assertEqual(plan.action, LOOKUP)
        self.assertEqual(plan.key, "What is your return policy? || How long does it take?")
        self.assertEqual([m["content"] for m in plan.messages],
                         ["What is your return policy?", "How long does it take?"])
        self.assertIsNotNone(plan.threshold)
        self.assertTrue(plan.shareable)
        self.assertEqual(plan.model_sees, "question + previous")

    def test_a_follow_up_with_nothing_before_it_goes_to_the_model(self):
        plan = Conversation().plan("How long does it take?")
        self.assertEqual((plan.action, plan.reason, plan.key), (MODEL, "no_prior_turn", None))
        self.assertFalse(plan.shareable)

    def test_a_follow_up_to_a_personal_turn_reads_the_whole_conversation(self):
        conv = Conversation()
        turn(conv, "Where is my order?", "It ships today.")
        plan = conv.plan("How long does it take?")
        self.assertIsNone(plan.messages)
        self.assertFalse(plan.shareable)
        self.assertEqual(plan.model_sees, "whole conversation")

    def test_a_personal_turn_with_no_values_is_never_looked_up(self):
        plan = Conversation().plan("I am a farmer, which schemes are best for me?")
        self.assertEqual((plan.action, plan.reason), (MODEL, "personal_no_values"))
        self.assertTrue(plan.personal)
        self.assertIsNone(plan.messages)
        self.assertFalse(plan.shareable)

    def test_a_personal_turn_with_values_looks_up_an_answer_shape(self):
        plan = Conversation(values={"order_id": "A-1"}).plan("When will my order arrive?")
        self.assertEqual(plan.action, LOOKUP)
        self.assertTrue(plan.template)
        self.assertFalse(plan.shareable)

    def test_short_empty_and_filler_turns(self):
        conv = Conversation(fillers={"thank you": "You're welcome."})
        self.assertEqual(conv.plan("").reason, "empty")
        self.assertEqual(conv.plan("um okay").reason, "short")
        filler = conv.plan("Thank you!")
        self.assertEqual((filler.action, filler.filler), (FILLER, "You're welcome."))

    def test_min_words_and_max_turns_are_validated(self):
        with self.assertRaises(ValueError):
            Conversation(min_words=0)
        with self.assertRaises(ValueError):
            Conversation(max_turns=0)


class SettleTests(unittest.TestCase):
    def test_a_general_answer_is_saved_under_its_key(self):
        saving = turn(Conversation(), "How long does shipping take?", "Shipping takes 3 to 5 days.")
        self.assertEqual(saving, Saving(SAVED, key="How long does shipping take?", text="Shipping takes 3 to 5 days."))
        self.assertTrue(saving.write)

    def test_a_personal_answer_is_private(self):
        saving = turn(Conversation(), "Where is my order?", "It ships today.")
        self.assertEqual(saving.outcome, PRIVATE)
        self.assertFalse(saving.write)

    def test_a_personal_answer_with_values_becomes_a_shape(self):
        conv = Conversation(values={"order_id": "A-1001", "eta": "Tuesday"})
        saving = turn(conv, "When will my order arrive?", "Your order A-1001 arrives on Tuesday.")
        self.assertEqual(saving.outcome, TEMPLATE)
        self.assertEqual(saving.text, "Your order {order_id} arrives on {eta}.")
        self.assertTrue(saving.template)

    def test_a_non_answer_is_never_saved(self):
        saving = turn(Conversation(), "How much is shipping?", "Could you tell me the destination?")
        self.assertEqual(saving.outcome, NON_ANSWER)

    def test_an_answer_carrying_a_declared_value_is_kept(self):
        conv = Conversation(values={"order_id": "A-1001"})
        saving = turn(conv, "How long does shipping take?", "For A-1001, shipping takes 3 days.")
        self.assertEqual(saving.outcome, KEPT)

    def test_a_short_turn_is_kept_and_an_empty_answer_is_not_saved(self):
        conv = Conversation()
        self.assertEqual(turn(conv, "shipping cost", "Shipping costs 5 dollars.").outcome, KEPT)
        self.assertEqual(turn(conv, "How long does shipping take?", "  ").outcome, NOT_SAVED)

    def test_an_unplanned_answer_is_never_shared(self):
        conv = Conversation()
        saving = conv.settle(conv.unplanned("How long does shipping take?"), "Three days.")
        self.assertEqual(saving.outcome, KEPT)


class ConversationStateTests(unittest.TestCase):
    def test_the_model_reads_the_whole_conversation_for_a_personal_turn(self):
        conv = Conversation()
        turn(conv, "Hi, I'm Rahul.", "Hello Rahul.")
        plan = conv.plan("What's my name?")
        self.assertEqual(conv.model_messages(plan, system="Be brief."), [
            {"role": "system", "content": "Be brief."},
            {"role": "user", "content": "Hi, I'm Rahul."},
            {"role": "assistant", "content": "Hello Rahul."},
            {"role": "user", "content": "What's my name?"},
        ])

    def test_nothing_said_earlier_reaches_a_general_question(self):
        conv = Conversation()
        turn(conv, "Hi, I'm Rahul and I'm a premium member.", "Hello Rahul.")
        plan = conv.plan("How long does shipping take?")
        messages = conv.model_messages(plan)
        self.assertEqual(messages, [{"role": "user", "content": "How long does shipping take?"}])
        self.assertNotIn("Rahul", str(messages))

    def test_max_turns_caps_the_history_a_model_call_carries(self):
        conv = Conversation(max_turns=2)
        for n in range(5):
            turn(conv, f"Where is my order number {n}?", f"Order {n} ships today.")
        messages = conv.model_messages(conv.plan("What did I order last time?"))
        self.assertEqual(len(messages), 2 * 2 + 1)
        self.assertEqual(messages[0]["content"], "Where is my order number 3?")
        self.assertEqual(len(conv.transcript), 10)  # the transcript itself is untouched

    def test_a_cache_hit_is_remembered_and_a_follow_up_builds_on_it(self):
        conv = Conversation()
        plan = conv.plan("What is your return policy?")
        self.assertEqual(conv.served(plan, "30 days."), "30 days.")
        self.assertEqual(conv.plan("How long does it take?").key,
                         "What is your return policy? || How long does it take?")

    def test_a_shape_with_an_unfillable_slot_is_not_served(self):
        conv = Conversation(values={"order_id": "C-3"})
        plan = conv.plan("When will my order arrive?")
        self.assertIsNone(conv.served(plan, "Order {order_id} arrives {eta}."))
        self.assertEqual(conv.transcript, [])

    def test_a_cancelled_turn_leaves_no_trace_and_is_not_saved(self):
        conv = Conversation()
        turn(conv, "What is your return policy?", "30 days.")
        plan = conv.plan("How long does shipping take?")
        self.assertTrue(conv.cancel())
        self.assertFalse(conv.cancel())
        self.assertEqual(conv.settle(plan, "Three days.").outcome, INTERRUPTED)
        self.assertEqual(len(conv.transcript), 2)

    def test_a_cancelled_cache_hit_is_rolled_back(self):
        conv = Conversation()
        plan = conv.plan("What is your return policy?")
        conv.served(plan, "30 days.")
        self.assertTrue(conv.cancel())
        self.assertEqual(conv.transcript, [])

    def test_keep_private_remembers_the_turn_and_saves_nothing(self):
        conv = Conversation()
        conv.plan("How long does shipping take?")
        self.assertTrue(conv.keep_private("How long does shipping take?", "Three days."))
        self.assertEqual(len(conv.transcript), 2)

    def test_a_plan_is_plain_data(self):
        plan = Conversation().plan("How long does shipping take?")
        self.assertIsInstance(plan, TurnPlan)
        with self.assertRaises(Exception):
            plan.key = "x"  # frozen


if __name__ == "__main__":
    unittest.main()
