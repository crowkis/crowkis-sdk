"""Server-free tests for the turn frame and the call state (turn understanding v2.2, part 1).

Run:  python -m pytest tests/ -q
"""

import unittest

from crowkis.callstate import CallState
from crowkis.turn import TurnFrame


def frame(**kw):
    base = {"kind": "general", "subject": "none", "confidence": 0.9, "question": "How long does shipping take?",
            "question_type": "policy", "entities": [], "attributes": {}}
    base.update(kw)
    return TurnFrame.from_dict(base)


class TurnFrameParsingTests(unittest.TestCase):
    def test_missing_or_garbage_output_is_not_shareable(self):
        for raw in (None, {}, {"kind": "banana"}, "not a dict"):
            f = TurnFrame.from_dict(raw)
            self.assertEqual(f.kind, "unclear")
            self.assertEqual(f.confidence, 0.0)
            self.assertIsNone(f.question)

    def test_identifying_comes_from_the_type_not_the_model(self):
        f = frame(entities=[{"text": "Sarah", "type": "person_name", "identifying": False}])
        self.assertTrue(f.entities[0].identifying)
        self.assertEqual(f.identifying_texts, ["Sarah"])

    def test_a_weekday_or_a_price_is_never_identifying(self):
        f = frame(entities=[{"text": "Saturday", "type": "time", "answer_relevant": True},
                            {"text": "10000 rupees", "type": "quantity", "answer_relevant": True}])
        self.assertEqual(f.identifying_texts, [])
        self.assertEqual([e.text for e in f.details], ["Saturday", "10000 rupees"])

    def test_confidence_is_clamped_and_bad_values_fail_closed(self):
        self.assertEqual(frame(confidence=7).confidence, 1.0)
        self.assertEqual(frame(confidence="high").confidence, 0.0)

    def test_dash_question_means_no_question(self):
        self.assertIsNone(frame(kind="personal", question="-").question)

    def test_attributes_accept_open_values_and_drop_empty_ones(self):
        f = frame(attributes={"segment": {"value": "Diamond Elite", "changes_answer": True},
                              "region": {"value": "none"}})
        self.assertEqual(f.attributes["segment"].value, "diamond elite")
        self.assertTrue(f.attributes["segment"].changes_answer)
        self.assertNotIn("region", f.attributes)

    def test_unknown_subject_on_a_non_general_turn_is_treated_as_about_the_caller(self):
        self.assertEqual(frame(kind="personal", subject="???").subject, "self")


class CallStateTests(unittest.TestCase):
    def test_a_verified_general_question_becomes_the_active_question(self):
        state = CallState()
        state.apply(frame(question="What are your support hours?"), shared=True)
        self.assertEqual(state.active_question, "What are your support hours?")

    def test_a_general_question_that_was_not_verified_does_not(self):
        state = CallState()
        state.apply(frame(question="What are your support hours?"), shared=False)
        self.assertIsNone(state.active_question)

    def test_fillers_never_change_the_state(self):
        state = CallState()
        state.apply(frame(question="What are your support hours?"), shared=True)
        before = state.snapshot()
        for _ in range(5):
            state.apply(frame(kind="chitchat", question="-"), shared=False)
            state.apply(frame(kind="dialogue", question="-"), shared=False)
        self.assertEqual(state.snapshot(), before)

    def test_a_greeting_that_names_a_place_is_remembered(self):
        state = CallState()
        state.apply(frame(kind="chitchat", question="-", confidence=0.5, entities=[
            {"text": "Park Winters", "type": "place"}]), shared=False)
        self.assertIn("place: Park Winters", state.facts)

    def test_an_abstain_clears_the_active_question_instead_of_guessing(self):
        state = CallState()
        state.apply(frame(question="What are your support hours?"), shared=True)
        state.apply(frame(kind="dialogue", abstain=True, question="-"), shared=False)  # no details at all
        self.assertIsNone(state.active_question)

    def test_agent_mentions_are_remembered_in_order_and_capped(self):
        state = CallState()
        state.note_agent_reply("How about Paciarino or the Corner Room?", mentions=["Paciarino", "The Corner Room"])
        self.assertEqual(state.agent_mentions, ["Paciarino", "The Corner Room"])
        state.note_agent_reply("more", mentions=[f"Place {i}" for i in range(20)])
        self.assertEqual(len(state.agent_mentions), 10)
        self.assertEqual(state.agent_mentions[-1], "Place 19")

    def test_facts_keep_only_non_identifying_details(self):
        state = CallState()
        state.apply(frame(kind="personal", subject="self", question="-", entities=[
            {"text": "phone case", "type": "product", "answer_relevant": True},
            {"text": "damaged", "type": "condition", "answer_relevant": True},
            {"text": "Rahul", "type": "person_name", "answer_relevant": True},
            {"text": "55512", "type": "id_number", "answer_relevant": True},
        ]), shared=False)
        self.assertEqual(state.facts, ["product: phone case", "condition: damaged"])

    def test_places_named_earlier_are_remembered_even_if_they_did_not_matter_then(self):
        state = CallState()
        state.apply(frame(question="What are the Sunday dinner hours at Park Winters?", entities=[
            {"text": "Park Winters", "type": "place", "answer_relevant": False}]), shared=False)
        self.assertIn("place: Park Winters", state.facts)

    def test_tier_and_location_last_the_whole_call(self):
        state = CallState()
        state.apply(frame(kind="personal", subject="self", question="-",
                          attributes={"segment": {"value": "premium", "changes_answer": True}}), shared=False)
        for _ in range(30):
            state.apply(frame(kind="chitchat", question="-"), shared=False)
        self.assertEqual(state.attributes["segment"].value, "premium")

    def test_task_status_is_set_by_the_app_and_cleared_by_a_fresh_question(self):
        state = CallState()
        state.note_agent_reply("Where would you like to stay?", task="booking")
        self.assertEqual(state.task, "booking")
        state.apply(frame(kind="dialogue", task_step=True, question="-",
                          entities=[{"text": "San Francisco", "type": "place"}]), shared=False)
        self.assertEqual(state.task, "booking")
        state.apply(frame(question="What is your cancellation policy?", task_step=False), shared=True)
        self.assertEqual(state.task, "none")

    def test_an_action_turn_starts_a_task_when_none_is_running(self):
        state = CallState()
        state.apply(frame(kind="action", subject="self", question="-"), shared=False)
        self.assertEqual(state.task, "account_action")

    def test_snapshot_has_no_caller_transcript_and_no_identity(self):
        state = CallState()
        state.set_identity("verified")
        state.apply(frame(kind="personal", subject="self", question="-", entities=[
            {"text": "Rahul", "type": "person_name"}]), shared=False)
        snap = state.snapshot()
        self.assertNotIn("identity", snap)
        self.assertNotIn("Rahul", str(snap))

    def test_identity_must_be_a_known_level(self):
        with self.assertRaises(ValueError):
            CallState().set_identity("trusted")


if __name__ == "__main__":
    unittest.main()
