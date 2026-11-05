"""v4 P5 item 3: the merged save check. Voice with an understander gains PrivateWord and ActionClaim;
Chat gains ToolResult, CallerIdentifier and the bounded write."""
import threading
import time
import unittest

from crowkis.channels.call_session import CallSession
from crowkis.state.call_state import CallState
from crowkis.understanding.model.frame import TurnFrame
from crowkis.understanding.slots import WordRuleClassifier

from test_voice_stress_bugs import Store, session_on

QUESTION = "What is your refund policy?"


class VoiceMergedSaveTests(unittest.TestCase):
    def test_a_word_from_a_private_turn_is_never_shared(self):
        store = Store()
        session = session_on(store, classifier=WordRuleClassifier())
        session.record(session.decide("my order 48213 for Sarah Khan has not arrived"), "I will check order 48213.")
        decision = session.decide("what is your refund policy")
        session.record(decision, "Sarah, refunds take five business days.")
        self.assertEqual(decision.save_rule, "VoicePrivateWord")
        self.assertEqual(store.shared, {})

    def test_an_answer_saying_it_was_done_is_never_shared(self):
        store = Store()
        session = session_on(store, classifier=WordRuleClassifier())
        decision = session.decide("what is your refund policy")
        session.record(decision, "I have cancelled your order and refunded you.")
        self.assertEqual(decision.save_rule, "VoiceActionClaim")
        self.assertEqual(store.shared, {})

    def test_f7_the_default_voice_rules_also_keep_an_action_claim_private(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        session.record(decision, "I have cancelled your order and refunded you.")
        self.assertEqual(decision.save_rule, "VoiceActionClaim")
        self.assertEqual(store.shared, {})


class Agent:
    def __init__(self, slow=0.0):
        self.slow = slow
        self.saved = []
        self.release = threading.Event()

    def ask(self, key, **kw):
        return {"route": "expensive", "answer": None, "confidence": 0.0}

    def learn(self, key, answer, ttl=None, template=False, segment=None):
        if self.slow:
            self.release.wait(self.slow)
        self.saved.append((key, answer))


class Scripted:
    def understand(self, turn, state):
        return TurnFrame.from_dict({"kind": "general", "subject": "none", "confidence": 0.9, "question": QUESTION,
                                    "question_type": "policy"})


class ChatMergedSaveTests(unittest.TestCase):
    def test_an_answer_built_from_a_tool_is_never_shared(self):
        agent = Agent()
        session = CallSession(agent, Scripted())
        result = session.handle("what is your refund policy")
        self.assertEqual(session.record_answer(result, "Your refund of 499 was sent.", private=True), "refused:tool_result")
        self.assertEqual(agent.saved, [])

    def test_an_answer_repeating_an_id_the_user_said_is_never_shared(self):
        agent = Agent()
        session = CallSession(agent, Scripted())
        session.handle("my order is ORD55821")
        result = session.handle("what is your refund policy")
        # PrivateWord refuses this first today (an ID turn is never shared); the identifiers are kept apart,
        # so the answer is still refused when the private words are gone.
        self.assertEqual(session.save_check("Refunds for ORD55821 take five days.", result.verdict), "private_word")
        session.state.private_words.clear()
        self.assertEqual(session.record_answer(result, "Refunds for ORD55821 take five days."), "refused:caller_identifier")

    def test_a_slow_server_costs_the_chat_one_write_not_a_stall(self):
        agent = Agent(slow=5)
        self.addCleanup(agent.release.set)
        session = CallSession(agent, Scripted(), latency_budget_ms=50)
        result = session.handle("what is your refund policy")
        started = time.monotonic()
        self.assertEqual(session.record_answer(result, "Refunds take five days."), "slow_write")
        self.assertLess(time.monotonic() - started, 1.0)
        self.assertEqual(session.stats()["slow_writes"], 1)

    def test_must_still_work_a_plain_answer_is_saved(self):
        agent = Agent()
        session = CallSession(agent, Scripted())
        result = session.handle("what is your refund policy")
        self.assertEqual(session.record_answer(result, "Refunds take five days."), "saved")
        self.assertEqual([answer for _, answer in agent.saved], ["Refunds take five days."])

    def test_a_refused_write_is_an_outcome_not_an_error(self):
        # v4 P5.5: the write's error boundary is the writer's; with and without a latency budget.
        for budget in (None, 50):
            agent = Agent()
            agent.learn = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("tenant limit"))
            session = CallSession(agent, Scripted(), latency_budget_ms=budget)
            result = session.handle("what is your refund policy")
            self.assertEqual(session.record_answer(result, "Refunds take five days."), "refused:write_failed")
            self.assertEqual(session.counts["save_refused"], 1)


class ExportTests(unittest.TestCase):
    def test_the_users_identifiers_are_exported_hashed(self):
        # Chat restores its state from the app's store each turn, so a later turn's check needs them (M2).
        # Hashed like the private words beside them: the raw value is never in the export.
        session = CallSession(Agent(), Scripted())
        session.handle("my order is ORD55821")
        exported = session.export()["state"]
        self.assertEqual(exported["identifiers"], session.state.identifiers)
        self.assertNotIn("55821", str(exported).lower())
        self.assertEqual(CallState.from_dict(exported).identifiers, session.state.identifiers)


if __name__ == "__main__":
    unittest.main()
