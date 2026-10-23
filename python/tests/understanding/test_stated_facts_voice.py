"""v4 P5 item 1: with an understander, StatedFacts replaces the call-wide taint. A later turn is shared
only when the model is sure no stated fact changes its answer; an allergy, a medication, a pregnancy
or an age always counts; unsure, late or no model: today's strict rule."""
import json
import unittest

from crowkis import LLMClassifier, LLMUnderstander

from test_voice_stress_bugs import Store, session_on

TRIP_TURN = "we are planning a trip to goa next month with the kids"
TRIP_FRAME = {"kind": "personal", "subject": "self", "confidence": 0.9,
             "entities": [{"text": "trip to goa", "type": "place", "identifying": False, "answer_relevant": True}]}
DEDUCTIBLE = {"kind": "general", "subject": "none", "confidence": 0.9, "question": "-"}


class Model:
    """Answers each turn with its scripted frame; remembers the call state it was sent."""

    def __init__(self, frames):
        self.frames = frames
        self.states = []

    def __call__(self, messages):
        payload = json.loads(messages[-1]["content"])
        self.states.append(payload["call_state"])
        return json.dumps(self.frames.get(payload["turn"], {"kind": "unclear"}))


def call_with(frames):
    model = Model(frames)
    store = Store()
    return model, store, session_on(store, classifier=LLMClassifier(LLMUnderstander(model)))


class VoiceStatedFactsTests(unittest.TestCase):
    def test_an_unrelated_stated_fact_no_longer_keeps_the_call_private(self):
        frames = {TRIP_TURN: TRIP_FRAME, "what is a deductible in insurance": dict(DEDUCTIBLE, fact_relevance=[
            {"fact": "place: trip to goa", "type": "trip", "changes_answer": False}])}
        _, store, session = call_with(frames)
        first = session.decide(TRIP_TURN)
        self.assertEqual(first.rule, "VoiceStatedFacts")
        session.record(first, "Goa is lovely in December.")
        later = session.decide("what is a deductible in insurance")
        self.assertTrue(later.cacheable)
        session.record(later, "A deductible is what you pay before insurance pays.")
        self.assertIn("what is a deductible in insurance", store.shared)
        self.assertNotIn(TRIP_TURN, store.shared)

    def test_a_relevant_stated_fact_keeps_the_later_turn_private(self):
        frames = {TRIP_TURN: TRIP_FRAME, "how do i file a claim": dict(DEDUCTIBLE, fact_relevance=[
            {"fact": "place: trip to goa", "type": "trip", "changes_answer": True}])}
        _, store, session = call_with(frames)
        session.record(session.decide(TRIP_TURN), "Goa is lovely in December.")
        later = session.decide("how do i file a claim")
        self.assertEqual(later.rule, "VoiceStatedFacts")
        self.assertFalse(later.cacheable)
        session.record(later, "Call us with your policy number.")
        self.assertEqual(store.shared, {})

    def test_an_allergy_always_counts(self):
        frames = {"which desserts do you have today": dict(DEDUCTIBLE, fact_relevance=[
            {"fact": "condition: peanuts", "type": "other", "changes_answer": False}])}
        _, _, session = call_with(frames)
        session.record(session.decide("I am allergic to peanuts"), "Noted.")
        self.assertFalse(session.decide("which desserts do you have today").cacheable)

    def test_the_model_reads_the_calls_facts_never_its_turns(self):
        model, _, session = call_with({TRIP_TURN: TRIP_FRAME})
        session.record(session.decide(TRIP_TURN), "Goa is lovely in December.")
        session.decide("what is a deductible in insurance")
        self.assertEqual(model.states[-1]["facts"], ["place: trip to goa"])
        self.assertNotIn("kids", json.dumps(model.states[-1]))

    def test_must_still_work_without_an_understander_the_call_is_tainted(self):
        store = Store()
        session = session_on(store)
        session.record(session.decide(TRIP_TURN), "Goa is lovely in December.")
        later = session.decide("what is a deductible in insurance")
        self.assertEqual(later.rule, "CallContextTaint")
        self.assertFalse(later.cacheable)


if __name__ == "__main__":
    unittest.main()
