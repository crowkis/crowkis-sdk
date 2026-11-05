"""F8 step 5: the F3 review leftovers, each with a test that failed before its fix."""
import unittest

from crowkis import voice_session
from crowkis.understanding.slots import WordReading
from conformance import ConformanceStore

FIRST = "what are your opening hours on sunday"
READ_AS_FOLLOW_UP = "do you ship to canada"
FOLLOW_UP = "how long does it take"


class ReadsOneTurnAsAFollowUp:
    """A classifier that reads a stand-alone-looking turn as a follow-up (the word rules do not)."""

    def classify(self, text, facts=()):
        class Reading(WordReading):
            is_context_dependent = text == READ_AS_FOLLOW_UP or WordReading(text).is_context_dependent
        return Reading(text)


class ChainTests(unittest.TestCase):
    def play(self):
        session = voice_session(client=ConformanceStore(), agent_id="leftovers", classifier=ReadsOneTurnAsAFollowUp())
        seen = []
        for said in (FIRST, READ_AS_FOLLOW_UP, FOLLOW_UP):
            decision = session.decide(said)
            seen.append(decision.messages)
            if decision.needs_model:
                session.record(decision, "Sure, yes.")
        return seen

    def test_a_turn_the_classifier_read_as_a_follow_up_does_not_root_a_later_chain(self):
        chain = [m["content"] for m in self.play()[-1]]
        self.assertEqual(chain, [FIRST, READ_AS_FOLLOW_UP, FOLLOW_UP])

    def test_must_still_work_a_stand_alone_turn_roots_the_chain(self):
        session = voice_session(client=ConformanceStore(), agent_id="leftovers")
        for said in (FIRST, FOLLOW_UP):
            decision = session.decide(said)
            if decision.needs_model:
                session.record(decision, "Sure, yes.")
        self.assertEqual([m["content"] for m in decision.messages], [FIRST, FOLLOW_UP])


if __name__ == "__main__":
    unittest.main()


class TemplateStore(ConformanceStore):
    def __init__(self):
        super().__init__()
        self.templates = []

    def cset(self, query, response, **kwargs):
        if kwargs.get("template"):
            self.templates.append((query, response))
        return super().cset(query, response, **kwargs)


class RecapTemplateTests(unittest.TestCase):
    VALUES = {"order_id": "A-1001", "eta": "Tuesday"}

    def play(self, said, answer):
        store = TemplateStore()
        session = voice_session(client=store, agent_id="leftovers", values=self.VALUES, share_templates=True)
        decision = session.decide(said)
        session.record(decision, answer)
        from crowkis.channels.voice_session import _wait_for_writes
        _wait_for_writes()
        return store.templates

    def test_a_recap_of_the_call_is_never_saved_as_a_template(self):
        self.assertEqual(self.play("What do you know about me?",
                                   "You are travelling to Lisbon with your sister. Order A-1001 arrives on Tuesday."), [])

    def test_must_still_work_an_order_status_is_still_saved_as_a_template(self):
        templates = self.play("Where is my order A-1001?", "Your order A-1001 arrives on Tuesday.")
        self.assertEqual(len(templates), 1)
        self.assertNotIn("A-1001", templates[0][1])


class EngineStore:
    """A server with a decision engine that has not judged the stored answer yet."""

    tenant = None

    def __init__(self, engine=True):
        self.engine = engine

    def cget_hit(self, query, **kwargs):
        from crowkis import CacheHit
        return CacheHit(response=b"Refunds take five days.", similarity=0.97, ttl_remaining=600, matched_key=b"k",
                        confidence=0.99, hit_type="semantic")

    def cdecision(self, query, **kwargs):
        return {"engine": self.engine}

    def ctoolget(self, *args, **kwargs):
        return None

    def close(self):
        pass


class FreshAgentTests(unittest.TestCase):
    def decide(self, engine):
        import time
        session = voice_session(client=EngineStore(engine), voice="alloy")
        deadline = time.monotonic() + 2
        while session.agent._decides is None and time.monotonic() < deadline:  # the factory asks off the call's path
            time.sleep(0.01)
        return session.decide("how much is the pro plan")

    def test_the_first_lookup_of_a_fresh_session_holds_a_reworded_unjudged_hit(self):
        held = self.decide(engine=True)
        self.assertEqual(held.action, "infer")
        self.assertIn("not been judged", held.reason)

    def test_must_still_work_without_an_engine_nothing_is_held(self):
        self.assertEqual(self.decide(engine=False).action, "serve")
