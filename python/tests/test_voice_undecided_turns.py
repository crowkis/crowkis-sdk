"""Caller turns the session never decided: a private turn kept with record_private_turn
(a LiveKit turn with RAG or CRM data, a realtime model), or history the app gave the
model before the call reached Crowkis. One that tells the call something a later answer
may depend on keeps the rest of the call off the shared cache, as a decided one does."""
import unittest

from crowkis import Agent, VoiceSession

from test_agent_voice import ScopedFakeClient

# What the caller told the call, then a question whose shared answer ignores it.
CASES = {
    "trip": ("I'm planning a trip to Goa in December.", "What should I pack?"),
    "language": ("Reply only in Hindi from now on.", "What is the capital of Japan?"),
    "child_age": ("I have a 3 year old daughter.", "What vaccines are due at this age?"),
}


def _session(client):
    return VoiceSession(Agent("caller", client=client), voice="v")


def _ask(session, question):
    seen = []

    def llm(messages):
        seen.append(messages)
        return "Here is the answer."

    return session.answer(question, llm), seen


class UndecidedTurnTests(unittest.TestCase):
    def _case(self, told, later, tell):
        client = ScopedFakeClient()
        client.shared[later] = "Another caller's plain answer."
        session = _session(client)
        tell(session, told)
        decision, seen = _ask(session, later)
        self.assertEqual(decision.action, "infer")
        self.assertIsNone(decision.messages, "the model must read the whole call")
        self.assertFalse(decision.cacheable)
        self.assertEqual(client.reads, [], "nothing is looked up")
        self.assertEqual(client.writes, [], "nothing is written")
        self.assertIn(told, [m["content"] for m in seen[-1]], "what was told reaches the model")

    def test_a_private_turn_that_tells_the_call_something_keeps_the_rest_off_the_shared_cache(self):
        for name, (told, later) in CASES.items():
            with self.subTest(case=name):
                self._case(told, later, lambda s, said: s.record_private_turn(said, "Noted."))

    def test_history_the_session_never_decided_keeps_the_rest_off_the_shared_cache(self):
        def heard(session, said):
            session.transcript.append({"role": "user", "content": said})  # the app's own history
            session._heard(said)

        for name, (told, later) in CASES.items():
            with self.subTest(case=name):
                self._case(told, later, heard)

    def test_plain_turns_keep_the_shared_cache(self):
        # Must still work: small talk, a question, a name or a number tell the call nothing.
        for said in ("what is your refund policy", "Hi, I have a question.", "I am Priya, account 4471.",
                     "Gracias, ¿me ayudas?"):
            with self.subTest(said=said):
                client = ScopedFakeClient()
                client.shared["What should I pack?"] = "Light clothes."
                session = _session(client)
                session.record_private_turn(said, "Sure.")
                session._heard(said)
                decision, _ = _ask(session, "What should I pack?")
                self.assertEqual(decision.action, "serve")
                self.assertNotEqual(client.reads, [])

    def test_a_turn_never_decided_is_judged_as_a_decided_one(self):
        for said in ("I'm allergic to peanuts.", "My son is 12 years old.", "Mumbai to Bangalore on the 14th.",
                     "मेरा सवाल है", "mujhe Hindi mein jawab do", "I have 2 orders", "I'm frustrated",
                     "check my order", "Gold member here, my plan renews in May", "x" * 5000):
            with self.subTest(said=said[:40]):
                decided = _session(ScopedFakeClient())
                decided.decide(said)
                heard = _session(ScopedFakeClient())
                heard._heard(said)
                self.assertEqual(heard._tainted, decided._tainted)

    def test_empty_or_missing_text_changes_nothing(self):
        client = ScopedFakeClient()
        client.shared["What should I pack?"] = "Light clothes."
        session = _session(client)
        for said in ("", "   ", None):
            session._heard(said)
        self.assertEqual(_ask(session, "What should I pack?")[0].action, "serve")

    def test_a_cancelled_turn_still_keeps_what_the_caller_said(self):
        # The caller said it, whatever happened to the answer: over-privacy only costs savings.
        session = _session(ScopedFakeClient())
        session.cancel()
        session._heard("Reply only in Hindi from now on.")
        self.assertTrue(session._tainted)


if __name__ == "__main__":
    unittest.main()
