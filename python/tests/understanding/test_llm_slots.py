"""v4 P4 step 4: the model-backed slots (LLMClassifier, LLMRewriter, ReplayRewriter) and a rewritten
turn's answer saved under the question it was looked up with."""
import json
import unittest

from crowkis import LLMClassifier, LLMRewriter, LLMUnderstander, ReplayRewriter
from crowkis.turn import TurnFrame
from crowkis.understanding.frame_reading import FrameReading
from crowkis.understanding.word_rule_classifier import WordRuleClassifier

from test_voice_stress_bugs import Store, session_on

GENERAL = {"kind": "general", "subject": "none", "confidence": 0.95, "question": "What is the refund policy?"}


class Model:
    """A stand-in for the app's LLM: answers every turn with ``frame`` and remembers what it was sent."""

    def __init__(self, frame=None, raw=None):
        self.frame = frame or GENERAL
        self.raw = raw
        self.sent = []

    def __call__(self, messages):
        self.sent.append(messages)
        return self.raw if self.raw is not None else json.dumps(self.frame)


def slots(model):
    understander = LLMUnderstander(model)
    return {"classifier": LLMClassifier(understander), "rewriter": LLMRewriter(understander)}


def reading(**frame):
    return FrameReading(TurnFrame.from_dict({**GENERAL, **frame}))


class FrameReadingTests(unittest.TestCase):
    def test_a_confident_general_turn_may_be_shared_under_its_question(self):
        self.assertFalse(reading().is_personal)
        self.assertEqual(reading().question, "What is the refund policy?")

    def test_anything_else_reads_as_personal_and_is_not_rewritten(self):
        for frame in ({"kind": "personal"}, {"kind": "live"}, {"kind": "action"}, {"kind": "sensitive"},
                      {"abstain": True}, {"urgent": True}, {"subject": "self"}, {"confidence": 0.3},
                      {"entities": [{"text": "48213", "type": "id_number", "identifying": True}]}):
            with self.subTest(frame=frame):
                self.assertTrue(reading(**frame).is_personal)
                self.assertIsNone(reading(**frame).question)

    def test_a_follow_up_depends_on_the_call(self):
        self.assertTrue(reading(uses_state=True).is_context_dependent)
        self.assertTrue(reading(kind="dialogue").is_context_dependent)
        self.assertFalse(reading().is_context_dependent)


class LLMSlotTests(unittest.TestCase):
    def test_a_rewritten_answer_is_saved_under_the_question_and_found_by_another_wording(self):
        store = Store()
        first = session_on(store, **slots(Model()))
        decision = first.decide("can you tell me about your refund policy")
        first.record(decision, "Refunds take five business days.")
        self.assertEqual(store.shared.get("What is the refund policy?"), "Refunds take five business days.")
        served = session_on(store, **slots(Model())).decide("how do refunds work at your store")
        self.assertEqual(served.action, "serve")

    def test_the_model_is_asked_once_per_turn(self):
        model = Model()
        session_on(Store(), **slots(model)).decide("whats ur refund policy pls")
        self.assertEqual(len(model.sent), 1)

    def test_the_model_sees_the_turn_alone(self):
        model = Model()
        session = session_on(Store(), **slots(model))
        session.record(session.decide("my name is Priya Sharma and I live in Pune"), "Hello Priya.")
        session.decide("whats ur refund policy pls")
        self.assertNotIn("Priya", json.dumps(model.sent[-1]))

    def test_output_that_is_not_a_frame_keeps_the_turn_private(self):
        store = Store()
        session = session_on(store, **slots(Model(raw="sorry, I cannot help")))
        decision = session.decide("whats ur refund policy pls")
        self.assertFalse(decision.cacheable)
        session.record(decision, "Refunds take five business days.")
        self.assertEqual(store.shared, {})

    def test_the_word_rules_still_apply_when_the_model_says_general(self):
        store = Store()
        session = session_on(store, **slots(Model()))
        decision = session.decide("my order 48213 has not arrived where is it")
        self.assertEqual(decision.rule, "OwnRecords")
        session.record(decision, "Order 48213 ships tomorrow.")
        self.assertEqual(store.shared, {})


class ReplayRewriterTests(unittest.TestCase):
    def test_an_exact_repeat_is_keyed_on_the_verified_question(self):
        rewriter = ReplayRewriter({"What is the refund policy?": "policy"})
        words = WordRuleClassifier().classify("what is the refund policy")
        self.assertEqual(rewriter.rewrite("what is the refund policy", words), "What is the refund policy?")

    def test_another_wording_keeps_the_callers_words(self):
        rewriter = ReplayRewriter({"What is the refund policy?": "policy"})
        words = WordRuleClassifier().classify("how do refunds work")
        self.assertIsNone(rewriter.rewrite("how do refunds work", words))

    def test_a_turn_read_as_personal_is_never_rewritten(self):
        rewriter = ReplayRewriter({"What is the refund policy?": "policy"})
        self.assertIsNone(rewriter.rewrite("what is the refund policy", reading(kind="personal")))

    def test_it_remembers_a_verified_question(self):
        rewriter = ReplayRewriter()
        rewriter.remember("refunds?", "What is the refund policy?")
        words = WordRuleClassifier().classify("Refunds?")
        self.assertEqual(rewriter.rewrite("Refunds?", words), "What is the refund policy?")


if __name__ == "__main__":
    unittest.main()
