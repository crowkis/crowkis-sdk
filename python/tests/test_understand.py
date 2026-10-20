"""Server-free tests for the understanding slot (turn understanding v2.2, part 3).

Run:  python -m pytest tests/ -q
"""

import json
import unittest

from crowkis.callstate import CallState
from crowkis.understand import LLMUnderstander, ReplayUnderstander, WithFallback
from crowkis.verify import SHARED, RuleChecker


class ReplayTests(unittest.TestCase):
    def test_an_exact_repeat_of_a_verified_question_is_recognised(self):
        replay = ReplayUnderstander({"What is your return policy?": "policy"})
        frame = replay.understand("what is your return policy", CallState())
        self.assertEqual(frame.kind, "general")
        self.assertEqual(frame.question, "What is your return policy?")
        verdict = RuleChecker().check(frame, "what is your return policy", CallState())
        self.assertTrue(verdict.shared)

    def test_anything_else_is_not_shared(self):
        replay = ReplayUnderstander({"What is your return policy?": "policy"})
        for turn in ("What is your return policy for Rahul?", "and how long does it take", "Thanks!"):
            frame = replay.understand(turn, CallState())
            self.assertFalse(RuleChecker().check(frame, turn, CallState()).shared, turn)

    def test_remembered_wordings_are_recognised_next_time(self):
        replay = ReplayUnderstander()
        replay.remember("Um, do you deliver on Sundays?", "Do you deliver on Sundays?", "policy")
        self.assertEqual(replay.understand("Do you deliver on Sundays", CallState()).question,
                         "Do you deliver on Sundays?")
        self.assertEqual(replay.understand("um do you deliver on sundays", CallState()).question,
                         "Do you deliver on Sundays?")


class LLMUnderstanderTests(unittest.TestCase):
    def test_a_well_formed_answer_becomes_a_frame_and_passes_the_checker(self):
        reply = {"kind": "general", "subject": "none", "confidence": 0.9, "question": "What time is check-in?",
                 "question_type": "policy", "entities": [{"text": "Sarah", "type": "person_name"}]}
        llm = LLMUnderstander(lambda messages: "Here you go:\n" + json.dumps(reply))
        turn = "What time is check-in? Sarah here."
        frame = llm.understand(turn, CallState())
        verdict = RuleChecker().check(frame, turn, CallState())
        self.assertEqual(verdict.route, SHARED)
        self.assertNotIn("Sarah", verdict.key)

    def test_garbage_output_fails_closed(self):
        llm = LLMUnderstander(lambda messages: "I think the caller wants shipping info.")
        frame = llm.understand("How long does shipping take?", CallState())
        self.assertEqual(frame.kind, "unclear")
        self.assertFalse(RuleChecker().check(frame, "How long does shipping take?", CallState()).shared)

    def test_the_prompt_carries_state_and_business_but_never_identity(self):
        seen = {}

        def complete(messages):
            seen["messages"] = messages
            return "{}"

        state = CallState(active_question="What are your support hours?")
        state.set_identity("verified")
        LLMUnderstander(complete, business="An online clothing store.").understand("What about weekends?", state)
        system, user = seen["messages"]
        self.assertIn("An online clothing store.", system["content"])
        payload = json.loads(user["content"])
        self.assertEqual(payload["call_state"]["active_question"], "What are your support hours?")
        self.assertNotIn("identity", payload["call_state"])
        self.assertEqual(payload["turn"], "What about weekends?")


class FallbackTests(unittest.TestCase):
    def test_a_failing_model_falls_back_to_replay(self):
        def broken(messages):
            raise TimeoutError("provider down")

        u = WithFallback(LLMUnderstander(broken), ReplayUnderstander({"Do you price match?": "policy"}))
        self.assertEqual(u.understand("Do you price match?", CallState()).question, "Do you price match?")
        self.assertEqual(u.primary_failures, 1)
        self.assertEqual(u.understand("Something new?", CallState()).kind, "unclear")

    def test_a_working_model_is_used(self):
        reply = json.dumps({"kind": "personal", "subject": "self", "confidence": 0.9, "question": "-"})
        u = WithFallback(LLMUnderstander(lambda m: reply), ReplayUnderstander())
        self.assertEqual(u.understand("Where is my order?", CallState()).kind, "personal")
        self.assertEqual(u.primary_failures, 0)


if __name__ == "__main__":
    unittest.main()
