"""The security audit of release/0.5.2 (14 Oct 2026): three ways a caller's details could
reach another caller. Same cases as node/test-voice-security-audit.js (the Pipecat one is
Python only, and runs against real Pipecat frames when pipecat-ai is installed).
"""

import asyncio
import unittest

from crowkis.agent import Agent
from crowkis.voice import VoiceSession

from test_agent_voice import ScopedFakeClient

ROOTS = (
    "Priya Sharma.", "Sharma, Priya.", "Anjali Verma.", "Delhi.", "Lupus.", "Gold member.", "Sixty five.",
    "Muslim.", "Bipolar.", "Schizophrenia.", "Twelve years old.", "Fourteen.", "Kosher.", "Halal food.",
)


def session(client, **kwargs):
    return VoiceSession(Agent("support", client=client), voice="v", **kwargs)


class SecurityAuditTests(unittest.TestCase):

    def test_a_template_never_carries_details_the_caller_did_not_declare(self):
        server = ScopedFakeClient()
        a = session(server, values={"order_id": "ORD-111"}, share_templates=True)
        a.answer("hello, my name is Priya Sharma", lambda m: "Hi Priya, how can I help?")
        a.answer(
            "when will my order arrive",
            lambda m: "Priya, your order ORD-111 is going to 42 Park Lane, and your balance is fifteen hundred rupees.",
        )
        self.assertEqual([w for w in server.writes if w["template"]], [])
        heard = session(server, values={"order_id": "ORD-222"}).decide("when will my order arrive")
        self.assertNotEqual(heard.action, "serve")
        # Each kind of undeclared detail on its own, with a declared value in the answer too.
        for answer in (
            "Your order {} arrives at 42 Park Lane.",
            "Your order {} arrives Tuesday; your balance is fifteen hundred rupees.",
            "Your order {} arrives Tuesday, we will email priya at gmail dot com.",
            "Your order {} arrives Tuesday, and the doctor says your pregnancy is fine.",
            "Priya, your order {} arrives Tuesday.",
        ):
            with self.subTest(answer=answer):
                server = ScopedFakeClient()
                s = session(server, values={"order_id": "ORD-111"}, share_templates=True)
                s.answer("hello, my name is Priya Sharma", lambda m: "Hi, how can I help?")
                s.answer("when will my order arrive", lambda m, a=answer: a.format("ORD-111"))
                self.assertEqual([w for w in server.writes if w["template"]], [])
        # Still shared when templates are on: an answer whose only detail is the declared value.
        server = ScopedFakeClient()
        s = session(server, values={"order_id": "ORD-111"}, share_templates=True)
        s.answer("when will my order arrive", lambda m: "Your order ORD-111 arrives on Tuesday.")
        self.assertEqual([w["response"] for w in server.writes if w["template"]], ["Your order {order_id} arrives on Tuesday."])

    def test_templates_are_off_by_default(self):
        question = "when will my order arrive"
        cases = (
            (["Priya."], question, "Priya, your order ORD-111 arrives Tuesday."),
            (["my name is priya sharma"], question, "Priya, your order ORD-111 arrives Tuesday."),
            (["i live in pune"], question, "Your order ORD-111 ships to Pune on Tuesday."),
            (["my wife anjali will collect it"], question, "Anjali can collect order ORD-111 on Tuesday."),
            (["me llamo josé"], question, "José, tu pedido ORD-111 llega el martes."),
            (["मेरा नाम प्रिया है"], "मेरा ऑर्डर कब आएगा", "प्रिया जी, आपका ऑर्डर ORD-111 मंगलवार को आएगा।"),
            ([], question, "Your order ORD-111 arrives on the third of March, Mrs Mehta."),
            ([], question, "Your order ORD-111 has nine items and arrives Tuesday."),
            (["i live on baker street"], question, "Your order ORD-111 goes to Baker Street on Tuesday."),
            ([], question, "Your order ORD-111 arrives in three to five days."),
        )
        for earlier, asked, answer in cases:
            with self.subTest(answer=answer):
                server = ScopedFakeClient()
                s = session(server, values={"order_id": "ORD-111"})
                for turn in earlier:
                    s.answer(turn, lambda m: "Okay.")
                s.decide(asked)
                self.assertEqual(s._record_model_turn(asked, answer), "private")
                self.assertEqual([w for w in server.writes if w["template"]], [])
        # On, the old behaviour holds.
        server = ScopedFakeClient()
        s = session(server, values={"order_id": "ORD-111"}, share_templates=True)
        s.decide(question)
        self.assertEqual(s._record_model_turn(question, "Your order ORD-111 arrives in three to five days."), "template")

    def test_a_short_or_unasked_reply_never_roots_a_shared_chain_or_is_stored_alone(self):
        for root in ROOTS:
            with self.subTest(root=root):
                server = ScopedFakeClient()
                s = session(server)
                s.answer(root, lambda m: "Okay.")
                s.answer("and what is the refund policy?", lambda m: "Refunds take 5 days.")
                self.assertEqual(server.writes, [])
        # Still shared: a question, and a follow-up to one.
        server = ScopedFakeClient()
        s = session(server)
        s.answer("What is the refund policy?", lambda m: "Refunds take 5 days.")
        s.answer("and for sale items?", lambda m: "The same.")
        self.assertEqual([w["query"] for w in server.writes],
                         ["What is the refund policy?", "What is the refund policy? || and for sale items?"])

    def test_a_detail_said_before_a_question_keeps_the_turn_private(self):
        for root in (
            "Gay, is that okay?", "Muslim, is the food halal?", "Bipolar, can you help?",
            "Twelve years old, can I sign up?", "Priya Sharma, can you help?", "Lupus, what do you cover?",
            "Fourteen, can I open an account?", "Gay couple, can we book a room?", "Jewish, do you serve kosher?",
            "Priya Sharma calling, is the store open?",
        ):
            with self.subTest(root=root):
                server = ScopedFakeClient()
                s = session(server)
                s.answer(root, lambda m: "Okay.")
                s.answer("and what is the refund policy?", lambda m: "Refunds take 5 days.")
                self.assertEqual(server.writes, [])
        # A greeting or an acknowledgement first is neither: still shared.
        for said in ("Hi, what are your hours?", "Okay, how do I reset my password?", "Thanks - what is the refund policy?"):
            with self.subTest(said=said):
                server = ScopedFakeClient()
                session(server).answer(said, lambda m: "Here you go.")
                self.assertEqual([w["query"] for w in server.writes], [said])

    def test_a_served_answer_filled_with_this_callers_values_is_not_shareable_audio(self):
        server = ScopedFakeClient()
        server.templates["when will my order arrive"] = "Your order {order_id} ships Tuesday."
        filled = session(server, values={"order_id": "ORD-111"}).decide("when will my order arrive")
        self.assertEqual(filled.action, "serve")
        self.assertFalse(filled.audio_shareable)
        server.shared["what are your opening hours"] = "Nine to five."
        plain = session(server).decide("what are your opening hours")
        self.assertTrue(plain.audio_shareable)
        with self.assertRaises(AttributeError):  # read-only
            plain.audio_shareable = False


try:
    from pipecat.frames import frames as F
    from pipecat.processors.aggregators.llm_context import LLMContext

    from crowkis.integrations.pipecat import crowkis_processors
except ImportError:
    crowkis_processors = None


@unittest.skipIf(crowkis_processors is None, "pipecat-ai not installed")
class PipecatPersonalAudioTests(unittest.TestCase):

    def test_the_gate_never_puts_a_filled_personal_answer_in_the_shared_audio_cache(self):
        class Server(ScopedFakeClient):
            def __init__(self):
                super().__init__()
                self.tools = {}

            def ctoolget(self, tool, key, *, tenant=None):
                return self.tools.get((tool, key))

            def ctoolset(self, tool, key, value, *, ex=None, tenant=None):
                self.tools[(tool, key)] = value

        server = Server()
        server.templates["when will my order arrive"] = "Your order {order_id} for {name} ships Tuesday."
        s = session(server, values={"order_id": "ORD-111", "name": "Priya Sharma"})
        gate, writeback, audio = crowkis_processors(s, sample_rate=24000)
        out = []

        async def capture(frame, direction=None):
            out.append(frame)

        for processor in (gate, writeback, audio):
            processor.push_frame = capture

        async def run():
            context = LLMContext(messages=[{"role": "user", "content": "when will my order arrive"}])
            await gate.process_frame(F.LLMContextFrame(context=context), None)
            speak = next(f for f in out if isinstance(f, F.TTSSpeakFrame))
            await writeback.process_frame(speak, None)
            for frame in (F.TTSStartedFrame(), F.TTSTextFrame(speak.text, aggregated_by="sentence"),
                          F.TTSAudioRawFrame(b"PCM-of-priya", 24000, 1), F.TTSStoppedFrame()):
                await audio.process_frame(frame, None)

        asyncio.run(run())
        self.assertEqual(server.tools, {})


if __name__ == "__main__":
    unittest.main()
