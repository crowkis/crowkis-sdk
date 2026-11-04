"""v4 P5 item 2: Chat runs the hit guards every channel runs (DifferentQuestion, CommitmentRewording on
exact questions only, PiiPlaceholder) and keeps the question each shared answer was saved for."""
import json
import time
import unittest

from crowkis.runtime.question_records import question_key
from crowkis.channels.call_session import CallSession
from crowkis.rules.chat_rule_set import ChatRuleSet
from crowkis.understanding.turn_frame import TurnFrame
from crowkis.turns.results import SHARED

QUESTION = "What are your opening hours on Sunday?"


class Server:
    """The key-value side the question records use."""

    tenant = "voice"

    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl=None):
        self.values[key] = value


class Agent:
    """A cache that returns ``hit`` for every question (None: a miss)."""

    def __init__(self, hit=None):
        self.hit = hit
        self._client = Server()
        self.saved = []

    def ask(self, key, **kw):
        if self.hit is None:
            return {"route": "expensive", "answer": None, "confidence": 0.0}
        return dict({"route": "cache", "confidence": 0.99}, **self.hit)

    def learn(self, key, answer, ttl=None, template=False, segment=None):
        self.saved.append((key, answer))


class Scripted:
    def understand(self, turn, state):
        return TurnFrame.from_dict({"kind": "general", "subject": "none", "confidence": 0.9, "question": QUESTION,
                                    "question_type": "policy"})


def ask(agent):
    session = CallSession(agent, Scripted())
    return session, session.handle("what are your opening hours on sunday")


class ChatHitGuardTests(unittest.TestCase):
    def test_a_commitment_is_served_only_for_the_exact_question(self):
        session, result = ask(Agent({"answer": "Refunds take 5 days.", "commitment": True, "exact": False}))
        self.assertTrue(result.needs_model)
        self.assertEqual(session.stats()["CommitmentRewording"], 1)
        _, exact = ask(Agent({"answer": "Refunds take 5 days.", "commitment": True, "exact": True}))
        self.assertEqual(exact.text, "Refunds take 5 days.")

    def test_an_answer_saved_for_a_different_question_is_not_served(self):
        agent = Agent({"answer": "We open at 10 on Saturdays."})
        agent._client.values[question_key("voice", "We open at 10 on Saturdays.")] = json.dumps(
            ["What are your opening hours on Saturday?"])
        session, result = ask(agent)
        self.assertTrue(result.needs_model)
        self.assertEqual(session.stats()["DifferentQuestion"], 1)

    def test_must_still_work_a_placeholder_is_never_served(self):
        _, result = ask(Agent({"answer": "Your order pii_card_ab12cd ships today."}))
        self.assertTrue(result.needs_model)

    def test_must_still_work_a_plain_hit_is_served(self):
        _, result = ask(Agent({"answer": "We open at 10 on Sundays."}))
        self.assertEqual((result.route, result.text), (SHARED, "We open at 10 on Sundays."))

    def test_a_saved_answer_keeps_its_question(self):
        agent = Agent()
        session, result = ask(agent)
        self.assertEqual(session.record_answer(result, "We open at 10 on Sundays."), "saved")
        key = question_key("voice", "We open at 10 on Sundays.")
        deadline = time.monotonic() + 2
        while key not in agent._client.values and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(json.loads(agent._client.values[key]), [QUESTION])

    def test_the_hit_chain_holds_no_rule_that_needs_more_than_a_chat_hit_has(self):
        # ConfidenceBar and ScreenOnlyAnswer read call.serve_above / call.channel, which ChatHitCall lacks.
        names = ChatRuleSet.hit_chain().names
        self.assertNotIn("ConfidenceBar", names)
        self.assertNotIn("ScreenOnlyAnswer", names)


if __name__ == "__main__":
    unittest.main()
