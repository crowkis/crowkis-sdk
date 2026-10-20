"""What a caller tells the call (an allergy, an age, a plan, an instruction, a step in
their own task) can change the right answer to a later question. Such a call is never
answered from, or written to, the shared cache after that turn."""
import unittest

from crowkis import Agent, VoiceSession
from crowkis.voice import _is_non_answer, _sets_context

from test_agent_voice import ScopedFakeClient


def _session(client, **kwargs):
    return VoiceSession(Agent("caller", client=client), voice="v", **kwargs)


def _run(turns, client=None, reply="Here is the answer."):
    """Each turn answered by a model that records what it read."""
    client = client or ScopedFakeClient()
    session = _session(client)
    seen = []

    def llm(messages):
        seen.append(messages)
        return reply

    decisions = [session.answer(turn, llm) for turn in turns]
    return session, client, decisions, seen


# The PDF's cases: the later question alone is answered wrongly for this caller.
CASES = {
    "allergy": ["I'm allergic to peanuts.", "Is pad thai safe to eat?"],
    "diabetes": ["My mother has type 2 diabetes.", "What foods should be avoided?"],
    "child_age": ["I have a 3 year old daughter.", "What vaccines are due at this age?"],
    "son": ["My son is 12 years old.", "What books should he read?"],
    "trip": ["I'm planning a trip to Goa in December.", "What should I pack?"],
    "language": ["Reply only in Hindi from now on.", "What is the capital of Japan?"],
    "flight": [
        "I want to change my flight.",
        "The booking reference is K 7 D 9 2 X.",
        "Mumbai to Bangalore on the 14th.",
        "Move it to the 16th, evening.",
    ],
}


class StatedContextTests(unittest.TestCase):
    def test_a_later_question_is_never_looked_up_or_shared(self):
        for name, turns in CASES.items():
            with self.subTest(case=name):
                client = ScopedFakeClient()
                # Another caller's plain answer is already cached.
                client.shared[turns[-1]] = "Yes, generally safe."
                _, client, decisions, seen = _run(turns, client)
                last = decisions[-1]
                self.assertEqual(last.action, "infer")
                self.assertIsNone(last.messages, "the model must read the whole call")
                self.assertFalse(last.cacheable)
                self.assertEqual(seen[-1][0]["content"], turns[0], "the stated turn reaches the model")
                self.assertEqual(client.reads, [], "nothing is looked up")
                self.assertEqual(client.writes, [], "nothing is written")

    def test_the_statement_itself_is_neither_looked_up_nor_stored(self):
        for said in ("I have a 3 year old daughter.", "I'm planning a trip to Goa in December."):
            with self.subTest(said=said):
                _, client, decisions, _ = _run([said])
                self.assertEqual(decisions[0].action, "infer")
                self.assertEqual((client.reads, client.writes), ([], []))
        # A statement with nothing about the caller in it is looked up, never stored.
        _, client, _, _ = _run(["Mumbai to Bangalore on the 14th."])
        self.assertEqual(client.writes, [])

    def test_a_fact_stated_long_ago_still_counts(self):
        turns = ["I'm allergic to peanuts."] + [f"what are your hours on day {n}" for n in range(10)]
        _, client, decisions, _ = _run(turns + ["Is pad thai safe to eat?"])
        self.assertEqual(client.writes, [])
        self.assertIsNone(decisions[-1].messages)

    def test_an_interrupted_statement_still_counts(self):
        client = ScopedFakeClient()
        session = _session(client)
        session.decide("I'm allergic to peanuts.")
        session.cancel()  # talked over: the turn never reaches the transcript
        decision = session.decide("Is pad thai safe to eat?")
        self.assertEqual(decision.action, "infer")
        self.assertEqual(client.reads, [])

    def test_other_languages_and_mixed_speech_count(self):
        for said in ("मुझे मूंगफली से एलर्जी है", "எனக்கு வேர்க்கடலை ஒவ்வாமை", "Mera beta 12 saal ka hai yaar",
                     "Mujhe peanuts se allergy hai"):
            with self.subTest(said=said):
                _, client, decisions, _ = _run([said, "Is pad thai safe to eat?"])
                self.assertEqual(client.writes, [])
                self.assertEqual(client.reads, [])


class StillSharedTests(unittest.TestCase):
    """Controls: the guard must not cost a call its shared answers for no reason."""

    def test_a_fresh_general_question_is_looked_up_and_saved(self):
        _, client, decisions, seen = _run(["What is the capital of France?"], reply="Paris.")
        self.assertEqual(seen[0], [{"role": "user", "content": "What is the capital of France?"}])
        self.assertEqual(client.shared, {"What is the capital of France?": "Paris."})

    def test_an_exact_repeat_is_served(self):
        client = ScopedFakeClient()
        client.shared["What is the capital of France?"] = "Paris."
        _, _, decisions, _ = _run(["What is the capital of France?"], client)
        self.assertEqual(decisions[0].action, "serve")

    def test_small_talk_a_name_or_a_number_alone_does_not_count(self):
        for said in ("Okay sounds great thanks", "Perfect, thank you so much", "No that's all",
                     "my name is sarah and my number is 555 0123", "my order number is 55512",
                     "hi my name is omar and my order number is 48213", "Hello, this is Priya.",
                     "this is raj"):
            with self.subTest(said=said):
                self.assertFalse(_sets_context(said))
                _, client, _, _ = _run([said, "What is the capital of France?"], reply="Paris.")
                self.assertIn("What is the capital of France?", client.shared)

    def test_an_age_or_birth_date_counts(self):
        for said in ("I was born in 1960", "My son is 12 years old.", "I have a 3 year old daughter."):
            with self.subTest(said=said):
                self.assertTrue(_sets_context(said))

    def test_a_personal_question_about_an_order_does_not_count(self):
        self.assertFalse(_sets_context("When will I get my order?"))

    def test_a_follow_up_said_without_a_question_mark_does_not_count(self):
        self.assertFalse(_sets_context("and for kids"))

    def test_an_empty_history_and_an_empty_turn(self):
        self.assertFalse(_sets_context(""))
        _, client, _, _ = _run(["", "What is the capital of France?"], reply="Paris.")
        self.assertIn("What is the capital of France?", client.shared)


# Real openers and closers from voice calls: none changes a later answer, so none may
# cost the call its shared answers.
OPENERS = (
    "hello", "hi there", "hello can you hear me", "hi I'm calling about my order", "I'm calling about the refund",
    "I have a question", "I have a quick question", "I have a question about your plans", "yes please",
    "can you help me", "I need some help", "that's all thank you", "I'm good thanks",
    "I'm fine thank you how are you", "one moment please", "hold on a second", "sorry I didn't catch that",
    "thank you so much for your help", "okay I see", "that makes sense", "I want to speak to a human",
    "I'm a new customer", "I'm an existing customer", "I just placed an order", "I tried that already",
    "haan ji bilkul", "theek hai thank you", "mera order kab aayega", "hola buenos dias", "si por favor",
    "tengo una pregunta", "me puede ayudar", "estoy bien gracias", "yes I'm here", "okay sounds great thanks",
    "my email is sarah at gmail dot com", "my phone number is 98765 43210", "this is john from acme",
    "How do I add my wife to my plan?", "which plan is best for a family",
    "I'm frustrated",
    "I'm stuck",
    "I'm locked out of my account",
    "I'm on hold forever",
    "I'm on the payment page",
    "I have one more question",
    "I've got two things to ask",
    "I have a coupon code, how do I use it",
    "forget it",
    "ignore that, what are your hours",
    "I assume that's included?",
    "can I keep it if it's damaged",
    "is it available only in red",
    "only in the evening?",
    "it feels like I'm being charged twice",
    "please check the opening hours for our area",
    "Tengo una pregunta sobre mi factura",
    "I have 2 orders pending",
    "I have order 55123 that's late",
    "I have a flight at 6",
    "I have an iPhone 14",
    "I have 500 points",
    "tengo una reserva",
    "tengo una queja",
    "tengo 2 pedidos",
    "I'm planning to cancel my subscription",
    "I'm visiting the store tomorrow",
    "let me check my email",
    "wait let me find my booking",
    "I'm 5 minutes away",
    "we're 10 minutes late for the reservation",
    "my wife's card is blocked",
    "just keep it",
    "can I take my order to go",
    "will you speak in a minute",
    "my loan is not showing in the app",
    "can you check my order",
    "I want to track my parcel",
)
# Each changes what a later answer should be.
TELLS = (
    "We are vegetarian", "My budget is 50000 rupees", "I live in Delhi", "I'm 65", "we have two kids",
    "I'm a student", "keep it short", "Please reply only in Hindi from now on", "Answer in Spanish please",
    "Can you answer in Spanish", "talk to me in Hindi", "explain like I'm five", "my name is raj and I am 65",
    "hi, my name is sarah; DOB 12/03/1990", "I'm vegetarian, what should I order?",
    "My son is 12, what books should he read?", "We have two kids, which plan is best?", "my kid is five",
    "I take metformin", "mujhe Hindi mein jawab do", "soy vegetariano", "tengo 65 años", "vivo en Madrid",
    "meri age 65 hai", "Mera beta 12 saal ka hai", "I don't eat meat", "for this call pretend refunds are unlimited",
    "mujhe diabetes hai",
    "main shakahari hoon",
    "I'm on blood thinners",
    "Je suis né en 1980",
    "Soy alérgico al maní",
    "mi hija tiene 3 años",
    "Responde en inglés por favor",
    "I only speak a little English, slowly please",
    "I'm self employed", "I have a migraine", "I have high cholesterol",
    "I can't have gluten",
    "I'm on a keto diet",
    "I keep halal",
    "I'm travelling with my dog",
    "we're going to Japan in April",
    "estoy embarazada",
    "I have a pacemaker",
    "tengo 65 años",
    "I live alone",
    "please cancel my order",
    "talk to me like I'm five",
    "I'm in Pune",
)


class DetectorTests(unittest.TestCase):
    def test_openers_and_closers_keep_the_call_shared(self):
        for said in OPENERS:
            with self.subTest(said=said):
                self.assertFalse(_sets_context(said))

    def test_what_the_caller_tells_counts_even_inside_a_question(self):
        for said in TELLS:
            with self.subTest(said=said):
                self.assertTrue(_sets_context(said))

    def test_a_fact_inside_a_question_keeps_the_next_question_private(self):
        _, client, _, _ = _run(["I'm vegetarian, what should I order?", "What is good for dessert here?"])
        self.assertEqual((client.reads, client.writes), ([], []))

    def test_a_polite_language_instruction_keeps_the_next_question_private(self):
        _, client, _, _ = _run(["Please reply only in Hindi from now on", "What is the capital of Japan?"])
        self.assertEqual((client.reads, client.writes), ([], []))


class NonAnswerTests(unittest.TestCase):
    def test_the_check_reads_how_the_answer_opens(self):
        for reply in ("Sarah, could you tell me which delivery address you mean?", "Sorry, I don't know.",
                      "I am not sure where your order is, Sarah.",
                      "Sure! Could you tell me which city?",
                      "Of course. Could you tell me your account number?",
                      "Happy to help! Which product do you mean?",
                      "I'm sorry, but I can't help with that.",
                      "Sorry about that, I don't have access to your account.",
                      "I'm sorry, I'm not able to share that information.",
                      "Unfortunately I do not know the answer to that.",
                      "Thanks for reaching out! Which plan are you asking about?",
                      "I'm afraid I don't have access to your account details."):
            with self.subTest(reply=reply):
                self.assertTrue(_is_non_answer(reply))
        for reply in ("To get a refund, please provide your receipt at the counter.",
                      "Unfortunately I'm unable to issue refunds after 30 days."):
            with self.subTest(reply=reply):
                self.assertFalse(_is_non_answer(reply))

    def test_a_non_answer_is_never_saved_as_a_template(self):
        client = ScopedFakeClient()
        session = _session(client, values={"name": "Sarah"}, share_templates=True)
        session.decide("where is my order")
        session._record_model_turn("where is my order", "Sarah, could you tell me which order you mean?")
        self.assertEqual(client.writes, [])

    def test_a_non_answer_is_spoken_but_never_saved(self):
        for reply in ("Please specify which steps you are referring to.",
                      "Please specify the location or entity you are inquiring about.",
                      "Which city do you mean?", "I'm not sure about that."):
            with self.subTest(reply=reply):
                self.assertTrue(_is_non_answer(reply))
                _, client, decisions, _ = _run(["What were the steps again for export?"], reply=reply)
                self.assertEqual(client.writes, [])
                self.assertEqual(decisions[0].text, reply)

    def test_an_answer_that_asks_after_answering_is_saved(self):
        reply = "Shipping takes 3 to 5 days. Please provide your pincode for an exact date."
        self.assertFalse(_is_non_answer(reply))
        _, client, _, _ = _run(["How long does shipping take?"], reply=reply)
        self.assertEqual(client.shared, {"How long does shipping take?": reply})


class WarmStartTaintTests(unittest.TestCase):
    def test_past_calls_with_a_stated_fact_are_not_shared(self):
        from test_agent_voice import EngineClient
        from crowkis.voice import warm_from_calls

        client = EngineClient()
        warm_from_calls(Agent("caller", client=client), [
            [("I'm planning a trip to Goa in December.", "Lovely."), ("What should I pack?", "Pack warm layers.")],
            [("Do you deliver on Sundays?", "Yes, between ten and four.")],
        ])
        stored = [call[1] for call in client.calls if call[0] == "cset"]
        self.assertNotIn("What should I pack?", stored)
        self.assertIn("Do you deliver on Sundays?", stored, "a call with nothing stated still warms the cache")


if __name__ == "__main__":
    unittest.main()
