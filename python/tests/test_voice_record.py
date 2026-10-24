"""VoiceSession.record(): save the answer from your own model call.

decide() then your model then record(decision, text) must do exactly what answer() does:
the same rules decide what is shared, kept to the call, or dropped. It only takes a
decision this session made for a model turn, once. answer() itself is unchanged."""

import unittest

from crowkis import Agent, CrowkisError, VoiceSession

from test_voice_stress_bugs import ANSWER, Store, session_on


def _fields(decision):
    return (decision.action, decision.text, decision.stored, decision.not_stored, decision.empty,
            decision.reason, decision.cacheable, decision.messages, decision.turn)


# Calls that exercise every rule: (turns, what the model says to each, session options).
CALLS = [
    (["what is your refund policy"], [ANSWER], {}),                                  # shared
    (["my order 48213 has not arrived where is it"], [ANSWER], {}),                   # personal
    (["what is your refund policy", "and how long does that take"], [ANSWER, ANSWER], {}),  # follow-up
    (["I am Priya Sharma", "what plan am I on"], [ANSWER, ANSWER], {}),               # private chain
    (["what is your refund policy"], [""], {}),                                       # empty answer
    (["what is your refund policy"], [None], {}),                                     # no answer
    (["how do I reset my password"], ["Your code is 4471, use it on the reset page."],
     {"values": {"code": "4471"}}),                                                    # leaks a value
    (["and what about that"], [ANSWER], {}),                                          # follow-up, nothing before
    (["refund kitne din mein milta hai"], [ANSWER], {}),                              # Hinglish
    (["\u092e\u0947\u0930\u093e \u0930\u093f\u092b\u0902\u0921 \u0915\u092c \u0906\u090f\u0917\u093e"], [ANSWER], {}),  # Devanagari: never shared
]


def _run(turns, replies, options, *, use_record, refuse=None):
    store = Store(refuse=refuse)
    session = session_on(store, **options)
    decisions = []
    for said, reply in zip(turns, replies):
        if use_record:
            decision = session.decide(said)
            if decision.needs_model:
                decision = session.record(decision, reply)
        else:
            decision = session.answer(said, lambda messages, reply=reply: reply)
        decisions.append(decision)
    return store, session, decisions


class SameAsAnswerTests(unittest.TestCase):
    def test_record_does_exactly_what_answer_does(self):
        for turns, replies, options in CALLS:
            with self.subTest(turns=turns, replies=replies):
                a_store, a_session, a_decisions = _run(turns, replies, options, use_record=False)
                r_store, r_session, r_decisions = _run(turns, replies, options, use_record=True)
                self.assertEqual(r_store.writes, a_store.writes)
                self.assertEqual(r_session.transcript, a_session.transcript)
                self.assertEqual(r_session.stats(), a_session.stats())
                self.assertEqual([_fields(d) for d in r_decisions], [_fields(d) for d in a_decisions])

    def test_a_refused_write_is_reported_the_same_and_never_raises(self):
        refuse = CrowkisError("ERR tenant cap reached")
        _, a_session, (a,) = _run(["what is your refund policy"], [ANSWER], {}, use_record=False, refuse=refuse)
        _, r_session, (r,) = _run(["what is your refund policy"], [ANSWER], {}, use_record=True, refuse=refuse)
        self.assertEqual(_fields(r), _fields(a))
        self.assertFalse(r.stored)
        self.assertIn("tenant cap", r.not_stored)
        self.assertEqual(r_session.learn_errors, 1)

    def test_record_returns_the_same_decision_filled_in(self):
        session = session_on(Store())
        decision = session.decide("what is your refund policy")
        self.assertIs(session.record(decision, ANSWER), decision)
        self.assertEqual((decision.text, decision.stored, decision.not_stored), (ANSWER, True, ""))


class GuardTests(unittest.TestCase):
    def test_a_turn_served_from_the_cache_cannot_be_recorded(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        session = session_on(store)
        served = session.decide("what is your refund policy")
        self.assertEqual(served.action, "serve")
        with self.assertRaises(ValueError) as caught:
            session.record(served, "something else")
        self.assertIn("model", str(caught.exception))
        self.assertEqual(store.writes, [])

    def test_a_filler_turn_cannot_be_recorded(self):
        session = session_on(Store(), fillers={"hello": "Hi, how can I help?"})
        filler = session.decide("hello")
        with self.assertRaises(ValueError):
            session.record(filler, ANSWER)

    def test_a_decision_from_another_session_is_refused(self):
        # Recording it here would put one caller's question into another caller's call.
        store = Store()
        one, other = session_on(store), session_on(store)
        decision = one.decide("what is your refund policy")
        with self.assertRaises(ValueError) as caught:
            other.record(decision, ANSWER)
        self.assertIn("another", str(caught.exception))
        self.assertEqual(store.writes, [])
        self.assertEqual(other.transcript, [])

    def test_a_decision_not_made_by_decide_is_refused(self):
        from crowkis import TurnDecision

        with self.assertRaises(ValueError):
            session_on(Store()).record(TurnDecision("infer"), ANSWER)

    def test_a_turn_is_recorded_once(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        session.record(decision, ANSWER)
        with self.assertRaises(ValueError) as caught:
            session.record(decision, "a second answer")
        self.assertIn("already", str(caught.exception))
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(len(session.transcript), 2)

    def test_answer_cannot_be_recorded_again(self):
        session = session_on(Store())
        decision = session.answer("what is your refund policy", lambda messages: ANSWER)
        with self.assertRaises(ValueError):
            session.record(decision, ANSWER)


class TurnRuleTests(unittest.TestCase):
    def test_after_a_barge_in_nothing_is_stored(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        session.cancel()
        session.record(decision, ANSWER)
        self.assertFalse(decision.stored)
        self.assertIn("moved on", decision.not_stored)
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript, [])

    def test_an_answer_to_an_older_turn_never_lands_on_later_words(self):
        store = Store()
        session = session_on(store)
        old = session.decide("what is your refund policy")
        session.decide("how do I reset my password")
        session.record(old, ANSWER)
        self.assertFalse(old.stored)
        self.assertIn("moved on", old.not_stored)
        self.assertEqual(store.writes, [])

    def test_private_keeps_a_shareable_answer_to_this_call(self):
        # E.g. an answer built from a tool's result: right for this caller only.
        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        self.assertTrue(decision.cacheable)
        session.record(decision, "Your refund of 40 dollars was approved today.", private=True)
        self.assertFalse(decision.stored)
        self.assertIn("tool", decision.not_stored)
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript[-1]["content"], "Your refund of 40 dollars was approved today.")

    def test_the_answer_is_spoken_with_the_whole_call_when_the_model_read_it(self):
        # A personal turn: the model reads the whole call and the answer is never shared.
        store = Store()
        session = session_on(store)
        decision = session.decide("my order 48213 has not arrived where is it")
        self.assertIsNone(decision.messages)
        session.record(decision, "Order 48213 left the depot this morning.")
        self.assertFalse(decision.stored)
        self.assertEqual(store.writes, [])


class AnswerUnchangedTests(unittest.TestCase):
    def test_answer_still_calls_the_model_with_the_chosen_messages(self):
        seen = []
        session = session_on(Store())
        decision = session.answer("what is your refund policy", lambda messages: seen.append(messages) or ANSWER,
                                  system="Be brief.")
        self.assertEqual(seen, [[{"role": "system", "content": "Be brief."},
                                 {"role": "user", "content": "what is your refund policy"}]])
        self.assertTrue(decision.stored)

    def test_a_served_turn_from_answer_never_calls_the_model(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        decision = session_on(store).answer("what is your refund policy",
                                            lambda messages: self.fail("the model was called"))
        self.assertEqual((decision.action, decision.text), ("serve", ANSWER))


class ReviewFollowUpTests(unittest.TestCase):
    def test_overlapping_decides_never_lend_a_newer_turn_the_older_flag(self):
        # Python pairs the flag with its turn; this guards it (Node had the bug).
        import threading
        import time

        class SlowStore(Store):
            def cget_hit(self, query, **kwargs):
                if "refund policy for orders" in query:
                    time.sleep(0.06)
                return super().cget_hit(query, **kwargs)

        for said in ("Twelve years old.", "The blue one, size nine please.", "and how long does that take"):
            with self.subTest(said=said):
                store = SlowStore()
                session = session_on(store)
                out = {}
                older = threading.Thread(target=lambda: out.setdefault("older", session.decide(
                    "what is your refund policy for orders")))
                older.start()
                time.sleep(0.01)
                out["newer"] = session.decide(said)
                older.join()
                newer = out["newer"]
                self.assertLess(out["older"].turn, newer.turn)
                session.record(newer, "Thanks Asha Rao, account 99812 is now updated.")
                self.assertFalse(newer.stored)
                self.assertEqual(store.writes, [])

    def test_answer_works_when_decide_is_overridden(self):
        from crowkis import TurnDecision

        class Custom(VoiceSession):
            def decide(self, caller_said):
                original = super().decide(caller_said)
                copy = TurnDecision(original.action, text=original.text, confidence=original.confidence,
                                    reason=original.reason)
                copy.messages, copy.cacheable, copy.turn = original.messages, original.cacheable, original.turn
                return copy

        store = Store()
        session = Custom(Agent("caller", client=store), voice="v")
        decision = session.answer("what is your refund policy", lambda messages: ANSWER)
        self.assertEqual(decision.text, ANSWER)
        self.assertEqual(store.writes, [("what is your refund policy", ANSWER, False)])

    def test_a_model_that_raises_records_nothing(self):
        store = Store()
        session = session_on(store)

        def broken(messages):
            raise RuntimeError("model down")

        with self.assertRaises(RuntimeError):
            session.answer("what is your refund policy", broken)
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript, [])

    def test_private_with_a_personal_turn_and_with_an_empty_answer(self):
        store = Store()
        session = session_on(store)
        decision = session.decide("my order 48213 has not arrived where is it")
        session.record(decision, "Order 48213 left the depot.", private=True)
        self.assertFalse(decision.stored)
        decision = session.decide("what is your refund policy")
        session.record(decision, "", private=True)
        self.assertTrue(decision.empty)
        self.assertEqual(store.writes, [])

    def test_something_that_is_not_a_decision_is_refused(self):
        session = session_on(Store())
        for wrong in (None, {"action": "infer"}, "infer"):
            with self.subTest(wrong=wrong), self.assertRaises(ValueError):
                session.record(wrong, ANSWER)

    def test_two_threads_recording_one_decision_write_it_once(self):
        import threading

        store = Store()
        session = session_on(store)
        decision = session.decide("what is your refund policy")
        errors = []
        start = threading.Barrier(2)

        def go():
            start.wait()
            try:
                session.record(decision, ANSWER)
            except ValueError as error:
                errors.append(error)

        threads = [threading.Thread(target=go) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(store.writes), 1)
        self.assertEqual(len(session.transcript), 2)

    def test_a_kept_decision_keeps_neither_the_call_nor_the_callers_words(self):
        import gc
        import weakref

        session = session_on(Store())
        decision = session.decide("what is your refund policy")
        session.record(decision, ANSWER)
        self.assertIsNone(decision._said)
        alive = weakref.ref(session)
        del session
        gc.collect()
        self.assertIsNone(alive())
        self.assertEqual(decision.text, ANSWER)

    def test_a_served_turn_does_not_carry_the_callers_words(self):
        store = Store()
        store.shared["what is your refund policy"] = ANSWER
        decision = session_on(store).decide("what is your refund policy")
        self.assertEqual(decision.action, "serve")
        self.assertIsNone(decision._said)


if __name__ == "__main__":
    unittest.main()
