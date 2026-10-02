"""Server-free tests for CallSession (turn understanding v2.2, part 4).

A fake Agent stands in for the cache; a scripted understander stands in for the model.
Run:  python -m pytest tests/ -q
"""

import time
import unittest

from crowkis.session import FILLER, CallSession
from crowkis.turn import TurnFrame
from crowkis.understand import ReplayUnderstander
from crowkis.verify import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT


class FakeAgent:
    def __init__(self, slow=0.0, broken=False):
        self.store, self.saved, self.slow, self.broken = {}, [], slow, broken

    def ask(self, key, **kw):
        if self.broken:
            raise ConnectionError("cache down")
        time.sleep(self.slow)
        if key in self.store:
            return {"route": "cache", "answer": self.store[key], "confidence": 0.99}
        return {"route": "expensive", "answer": None, "confidence": 0.0}

    def learn(self, key, answer, ttl=None, template=False):
        self.store[key] = answer
        self.saved.append((key, answer, ttl))


class Scripted:
    """Returns a prepared frame per turn text."""

    def __init__(self, frames):
        self.frames = frames

    def understand(self, turn, state):
        return TurnFrame.from_dict(self.frames.get(turn))


def general(question, **kw):
    d = {"kind": "general", "subject": "none", "confidence": 0.9, "question": question, "question_type": "policy"}
    d.update(kw)
    return d


class RoutingTests(unittest.TestCase):
    def test_miss_then_save_then_hit_for_the_next_caller(self):
        agent = FakeAgent()
        frames = {"How long does shipping take?": general("How long does shipping take?")}
        first = CallSession(agent, Scripted(frames))
        r = first.handle("How long does shipping take?")
        self.assertEqual((r.route, r.needs_model), (SHARED, True))
        self.assertEqual(r.messages, [{"role": "user", "content": "How long does shipping take?"}])
        self.assertEqual(first.record_answer(r, "Shipping takes 3 to 5 days."), "saved")

        second = CallSession(agent, Scripted(frames))
        r2 = second.handle("How long does shipping take?")
        self.assertTrue(r2.served_from_cache)
        self.assertEqual(r2.text, "Shipping takes 3 to 5 days.")

    def test_the_model_never_reads_the_callers_name_on_a_shared_miss(self):
        frames = {"What time is check-in? Sarah here.": general(
            "What time is check-in?", entities=[{"text": "Sarah", "type": "person_name"}])}
        r = CallSession(FakeAgent(), Scripted(frames)).handle("What time is check-in? Sarah here.")
        self.assertNotIn("Sarah", str(r.messages))

    def test_urgent_calls_the_hook_first_and_is_never_cached(self):
        seen = []
        frames = {"I smell gas in my kitchen.": {"kind": "sensitive", "subject": "self", "urgent": True}}
        s = CallSession(FakeAgent(), Scripted(frames), on_urgent=lambda t, f: seen.append(t))
        r = s.handle("I smell gas in my kitchen.")
        self.assertEqual(r.route, URGENT)
        self.assertEqual(seen, ["I smell gas in my kitchen."])
        self.assertEqual(s.record_answer(r, "Please leave the house and call emergency services."), "not_shared")

    def test_a_broken_urgent_hook_does_not_end_the_call(self):
        def boom(t, f):
            raise RuntimeError("pager down")

        frames = {"I fell and can't get up.": {"kind": "sensitive", "subject": "self", "urgent": True}}
        r = CallSession(FakeAgent(), Scripted(frames), on_urgent=boom).handle("I fell and can't get up.")
        self.assertEqual(r.route, URGENT)

    def test_each_kind_goes_to_its_route(self):
        frames = {
            "Where is my order?": {"kind": "personal", "subject": "self", "confidence": 0.9},
            "Cancel my order.": {"kind": "action", "subject": "self", "confidence": 0.9},
            "Thanks!": {"kind": "chitchat"},
        }
        s = CallSession(FakeAgent(), Scripted(frames))
        self.assertEqual(s.handle("Where is my order?").route, PERSONAL)
        self.assertEqual(s.handle("Cancel my order.").route, TOOLS)
        self.assertEqual(s.handle("Thanks!").route, AGENT)

    def test_task_steps_go_to_the_agent_and_are_never_saved(self):
        agent = FakeAgent()
        frames = {"Under 100 dollars for two.": general("Which restaurants cost under 100 dollars for two?")}
        s = CallSession(agent, Scripted(frames))
        s.state.note_agent_reply("What is your budget?", task="booking")
        r = s.handle("Under 100 dollars for two.")
        self.assertEqual(r.route, TASK)
        s.record_answer(r, "Got it, under 100 for two.")
        self.assertEqual(agent.saved, [])

    def test_fillers_are_answered_locally(self):
        s = CallSession(FakeAgent(), Scripted({}), fillers={"thank you": "You're welcome."})
        r = s.handle("Thank you!")
        self.assertEqual((r.route, r.text, r.needs_model), (FILLER, "You're welcome.", False))

    def test_a_failing_understander_means_the_agent_answers(self):
        class Broken:
            def understand(self, turn, state):
                raise RuntimeError("model down")

        s = CallSession(FakeAgent(), Broken())
        r = s.handle("How long does shipping take?")
        self.assertEqual(r.route, AGENT)
        self.assertEqual(s.stats()["understand_errors"], 1)

    def test_a_slow_or_broken_cache_falls_back_to_the_model(self):
        frames = {"Do you price match?": general("Do you price match?")}
        slow = CallSession(FakeAgent(slow=0.5), Scripted(frames), latency_budget_ms=50)
        r = slow.handle("Do you price match?")
        self.assertEqual((r.route, r.needs_model), (SHARED, True))
        self.assertEqual(slow.stats()["lookup_timeouts"], 1)
        broken = CallSession(FakeAgent(broken=True), Scripted(frames))
        self.assertTrue(broken.handle("Do you price match?").needs_model)
        self.assertEqual(broken.stats()["lookup_errors"], 1)

    def test_verified_questions_feed_the_safe_fallback(self):
        replay = ReplayUnderstander()
        frames = {"Um, do you deliver on Sundays?": general("Do you deliver on Sundays?")}
        CallSession(FakeAgent(), Scripted(frames), replay=replay).handle("Um, do you deliver on Sundays?")
        self.assertEqual(replay.understand("do you deliver on sundays", None).question, "Do you deliver on Sundays?")


class UnderstandBudgetTests(unittest.TestCase):
    class Slow:
        def __init__(self, delay, frame):
            self.delay, self.frame = delay, frame

        def understand(self, turn, state):
            time.sleep(self.delay)
            return TurnFrame.from_dict(self.frame)

    def test_a_slow_model_is_cut_off_and_the_agent_answers(self):
        s = CallSession(FakeAgent(), self.Slow(0.5, general("Do you price match?")), understand_budget_ms=50)
        started = time.monotonic()
        r = s.handle("Do you price match?")
        self.assertLess(time.monotonic() - started, 0.3)
        self.assertEqual(r.route, AGENT)
        self.assertEqual(s.stats()["understand_timeouts"], 1)

    def test_a_slow_model_falls_back_to_exact_repeats(self):
        replay = ReplayUnderstander({"Do you price match?": "policy"})
        s = CallSession(FakeAgent(), self.Slow(0.5, general("Do you price match?")), replay=replay,
                        understand_budget_ms=50)
        r = s.handle("Do you price match?")
        self.assertEqual(r.route, SHARED)
        self.assertEqual(s.stats()["fallback_used"], 1)

    def test_a_model_within_budget_is_used(self):
        s = CallSession(FakeAgent(), self.Slow(0.01, general("Do you price match?")), understand_budget_ms=500)
        self.assertEqual(s.handle("Do you price match?").route, SHARED)
        self.assertEqual(s.stats()["understand_timeouts"], 0)

    def test_a_late_model_never_sees_a_later_turns_state(self):
        seen = []

        class Peek:
            def understand(self, turn, state):
                time.sleep(0.2)
                seen.append(state.active_question)
                return TurnFrame.from_dict(None)

        s = CallSession(FakeAgent(), Peek(), understand_budget_ms=20)
        s.handle("first")
        s.state.active_question = "changed later"
        time.sleep(0.3)
        self.assertEqual(seen, [None])

    def test_budgets_must_be_positive(self):
        with self.assertRaises(ValueError):
            CallSession(FakeAgent(), Scripted({}), understand_budget_ms=0)


class ProductionControlTests(unittest.TestCase):
    FRAMES = {"Do you price match?": general("Do you price match?")}

    def test_the_kill_switch_stops_all_sharing_at_runtime(self):
        agent = FakeAgent()
        s = CallSession(agent, Scripted(self.FRAMES))
        s.set_mode("off")
        r = s.handle("Do you price match?")
        self.assertEqual(r.route, AGENT)
        self.assertEqual(s.record_answer(r, "Yes, we match prices."), "not_shared")
        self.assertEqual(agent.saved, [])
        s.set_mode("full")
        self.assertEqual(s.handle("Do you price match?").route, SHARED)

    def test_replay_only_mode_never_calls_the_model(self):
        class Exploding:
            def understand(self, turn, state):
                raise AssertionError("model must not be called")

        replay = ReplayUnderstander({"Do you price match?": "policy"})
        s = CallSession(FakeAgent(), Exploding(), replay=replay, mode="replay_only")
        self.assertEqual(s.handle("Do you price match?").route, SHARED)
        self.assertEqual(s.handle("Something new?").route, AGENT)

    def test_unknown_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            CallSession(FakeAgent(), Scripted({}), mode="yolo")

    def test_monitoring_events_carry_decisions_but_never_raw_words(self):
        events = []
        frames = {"What time is check-in? Sarah here.": general(
            "What time is check-in?", entities=[{"text": "Sarah", "type": "person_name"}])}
        s = CallSession(FakeAgent(), Scripted(frames), on_event=events.append)
        r = s.handle("What time is check-in? Sarah here.")
        s.record_answer(r, "Check-in is at 2 PM.")
        self.assertEqual([e["type"] for e in events], ["turn", "answer"])
        self.assertEqual(events[0]["route"], SHARED)
        self.assertEqual(events[1]["outcome"], "saved")
        self.assertNotIn("Sarah", str(events))

    def test_a_broken_monitoring_hook_does_not_affect_the_call(self):
        def boom(event):
            raise RuntimeError("dashboard down")

        s = CallSession(FakeAgent(), Scripted(self.FRAMES), on_event=boom)
        r = s.handle("Do you price match?")
        self.assertEqual(s.record_answer(r, "Yes, we match prices."), "saved")


class SaveCheckTests(unittest.TestCase):
    def setUp(self):
        self.agent = FakeAgent()
        self.frames = {"How do I return an item?": general("How do I return an item?")}

    def answer(self, text, session=None):
        s = session or CallSession(self.agent, Scripted(self.frames))
        return s.record_answer(s.handle("How do I return an item?"), text)

    def test_a_real_answer_is_saved_with_the_type_expiry(self):
        self.assertEqual(self.answer("Go to Orders, pick the item and choose Return."), "saved")
        self.assertIsNone(self.agent.saved[0][2])  # policy/how-to: until the knowledge version changes

    def test_non_answers_are_not_saved(self):
        self.assertEqual(self.answer("Could you tell me which item?"), "refused:non_answer")

    def test_action_claims_are_not_saved(self):
        self.assertEqual(self.answer("I've cancelled that for you."), "refused:action_claim")
        self.assertEqual(self.answer("Your order has been refunded."), "refused:action_claim")

    def test_identifying_details_are_not_saved(self):
        self.assertEqual(self.answer("Email returns@example.com with order 5551234."), "refused:identifying")

    def test_a_tier_not_in_the_key_cannot_appear_in_the_saved_answer(self):
        s = CallSession(self.agent, Scripted(self.frames))
        s.state.apply(TurnFrame.from_dict({"kind": "personal", "subject": "self",
                                           "attributes": {"segment": {"value": "premium"}}}), shared=False)
        self.assertEqual(self.answer("Premium members can return within 60 days.", s), "refused:attribute_not_in_key")


class BargeInTests(unittest.TestCase):
    def test_a_cancelled_turn_is_never_saved(self):
        agent = FakeAgent()
        s = CallSession(agent, Scripted({"Do you price match?": general("Do you price match?")}))
        r = s.handle("Do you price match?")
        self.assertTrue(s.cancel())
        self.assertEqual(s.record_answer(r, "Yes, we match any listed price."), "cancelled")
        self.assertEqual(agent.saved, [])

    def test_an_old_turn_finishing_late_is_never_saved(self):
        agent = FakeAgent()
        frames = {"Do you price match?": general("Do you price match?"),
                  "Do you ship to Canada?": general("Do you ship to Canada?")}
        s = CallSession(agent, Scripted(frames))
        old = s.handle("Do you price match?")
        new = s.handle("Do you ship to Canada?")
        self.assertEqual(s.record_answer(old, "Yes, we match prices."), "stale")
        self.assertEqual(s.record_answer(new, "Yes, we ship to Canada."), "saved")
        self.assertEqual([k for k, _, _ in agent.saved], ["[kb=1] Do you ship to Canada?"])


class PersonalShapeTests(unittest.TestCase):
    def test_a_verified_value_is_phrased_only_at_the_required_identity(self):
        s = CallSession(FakeAgent(), Scripted({}))
        s.register_shape("balance", "Your balance is {balance}.", requires="verified")
        self.assertIsNone(s.phrase("balance", "₹2,400"))
        s.state.set_identity("identified")
        self.assertIsNone(s.phrase("balance", "₹2,400"))
        s.state.set_identity("verified")
        self.assertEqual(s.phrase("balance", "₹2,400"), "Your balance is ₹2,400.")

    def test_never_phrased_for_someone_else(self):
        s = CallSession(FakeAgent(), Scripted({}))
        s.register_shape("eta", "Your order arrives on {eta}.")
        s.state.set_identity("verified")
        self.assertIsNone(s.phrase("eta", "Tuesday", subject="other"))

    def test_a_shape_must_carry_its_own_slot(self):
        with self.assertRaises(ValueError):
            CallSession(FakeAgent(), Scripted({})).register_shape("eta", "Your order arrives soon.")


if __name__ == "__main__":
    unittest.main()
