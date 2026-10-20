"""One test per finding of the independent review of the voice bug-fix (14 Oct 2026).

Each runs the reviewer's own turns through the path a user takes (VoiceSession.answer,
or the Pipecat processors), with a fake client standing in for the server, next to
"must still work" controls for the opposite case. Same cases as
node/test-voice-review-fixes.js.
"""

import asyncio
import logging
import time
import unittest

from crowkis.agent import Agent
from crowkis.voice import VoiceSession, _is_personal

from test_voice_stress_bugs import ANSWER, Store, _pipecat, call, session_on, user


class ReviewFixTests(unittest.TestCase):

    def assertKeptPrivate(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertFalse(decisions[-1].cacheable, said)
        self.assertTrue(all(said not in query for query, _, _ in store.writes), (said, store.writes))

    def assertShared(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertTrue(decisions[-1].cacheable, said)
        self.assertIn((said, ANSWER, False), store.writes, said)
        self.assertFalse(_is_personal(said), said)

    def assertFollowsThePrivateTurn(self, turns):
        """The last turn is answered with the whole call in view, and nothing of it is stored."""
        store, _, decisions, seen = call(*turns)
        self.assertIsNone(decisions[-1].messages, turns)
        self.assertFalse(decisions[-1].cacheable, turns)
        self.assertEqual(seen[-1][0], user(turns[0]), turns)
        self.assertEqual(seen[-1][-1], user(turns[-1]), turns)
        self.assertTrue(all(turns[-1] not in query for query, _, _ in store.writes), turns)

    def test_review_01_a_first_person_disclosure_keeps_a_how_to_private(self):
        for said in (
            "I'm pregnant, what should I do about the nausea?",
            "My doctor prescribed 50mg of sertraline, what should I do if I miss a dose?",
            "I'm HIV positive, how do I get the medicine?",
            "I'm allergic to penicillin, what should I do if I get a rash?",
            "My lawyer told me to sue, how do I file?",
            "My husband hits me, where can I go?",
            "I have HIV, can I still donate blood?",
            "My son was arrested last night, what do I do?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said), said)
        # The same words in a generic framing are still shared.
        for said in (
            "How do I find a good lawyer?",
            "What should I do if a doctor is late?",
            "What should I bring to a first consultation with a lawyer?",
            "How can I improve my sleep?",
            "How do I add my wife to my plan?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_review_02_names_in_any_form_are_private(self):
        for said in (
            "I am Priya Sharma.",
            "Priya speaking, I need help.",
            "Can Priya Sharma pick up the parcel?",
            "Does Mohit have an appointment tomorrow?",
            "Refund status for Rahul Verma",
            "Is the order for Rahul ready?",
            "When is Dr Mehta's appointment for Anjali?",
            "Mi nombre es Carlos.",
            "Je m'appelle Pierre.",
            "Hola, soy Carlos.",
            "Mein Name ist Hans.",
            "Hi, it's Priya again.",
            # Transcripts may come lowercase.
            "i am priya sharma",
            "this is priya",
            "priya here",
            "hola soy carlos",
            "je m'appelle pierre",
            "mera naam rahul hai",
            "me llamo carlos",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said), said)
        # Product names, weekdays, months and places said in passing are not names.
        for said in (
            "Can I pay with Apple Pay at the counter?",
            "Can I use Google Maps to find the store?",
            "What is included in the Premium plan?",
            "Are you open on Monday?",
            "Is the café open on Sundays?",
            "Do you have a sale in December?",
            "Do you deliver to Mumbai?",
            "How long does it take to deliver to Pune?",
            "Is there a store in London?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_review_03_numbers_dates_emails_and_addresses_are_private(self):
        for said in (
            "Is 4409 the right PIN?",
            "My PIN is 4409, how do I change it?",
            "Is forty four oh nine the right PIN?",
            "Was I born on 12/03/1985?",
            "I was born on March 12 1985, can you check?",
            "Track order seven four two please",
            "Where is order 742?",
            "Is priya sharma at gmail the email on file?",
            "Is john at gmail a valid email?",
            "Its j o h n at yahoo",
            "I live at 42 Park Lane, do you deliver there?",
            "I need an ambulance at 42 Park Lane",
            "Can you send it to 221B Baker Street?",
            "I'm 45, can I take ibuprofen?",
            "I earn fifty thousand a month, how much loan can I get?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said), said)
        for said in (
            "What happened in 1985?",
            "Is the store open 24 hours?",
            "Do you have a 2 year warranty?",
            "What are the top 10 features?",
            "Is the 1,499 plan good for families?",
            "How much is a 2 kg parcel to Delhi?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_review_04_a_short_follow_up_to_an_emergency_keeps_the_emergency(self):
        for turns in (
            ("My father collapsed!", "What happens now?"),
            ("My father collapsed!", "Is he going to be okay?"),
            ("My father collapsed!", "Should I give him water?"),
            ("My child swallowed a battery", "How do I make her vomit?"),
            ("I took 20 pills", "What happens now?"),
            ("She is bleeding a lot", "What do I do?"),
            ("I'm pregnant", "Which painkiller is safe?"),
            ("My father collapsed!", "Is he going to be okay?", "What happens now?"),
        ):
            with self.subTest(turns=turns):
                self.assertFollowsThePrivateTurn(turns)
        # After a generic turn, "should I restart it?" behaves as before: shared, alone.
        store, _, decisions, seen = call("What are your opening hours?", "Should I restart it?")
        self.assertTrue(decisions[-1].cacheable)
        self.assertEqual(seen[-1], [user("Should I restart it?")])
        self.assertIn(("Should I restart it?", ANSWER, False), store.writes)

    def test_review_05_a_confirmation_or_a_question_about_this_call_is_never_shared(self):
        for said in (
            "Sounds good to me.",
            "Let's do that then.",
            "Lock it in.",
            "What did you just say?",
            "Repeat the last answer.",
            "What did we talk about?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said, "Do you have a table for two at 8 pm?")
                self.assertKeptPrivate(said)
        self.assertShared("What did the update change?")

    def test_review_06_possessives_in_other_latin_script_languages_are_private(self):
        for said in (
            "Où est ma commande numéro 4409?",
            "Où sont mes commandes?",
            "Notre commande est en retard?",
            "¿Dónde está mi pedido?",
            "¿Dónde está nuestro pedido?",
            "Cadê meu pedido?",
            "Onde está minha encomenda?",
            "Wo ist meine Bestellung?",
            "Hamara order kab aayega?",
            "Humara order kab aayega?",
            "Apna order kab aayega?",
            "Mai order kab aayega?",
            "Main order kab aayega?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
                self.assertTrue(_is_personal(said), said)
        for said in ("What is the main difference between the plans?", "¿Cuánto cuesta el plan premium?"):
            with self.subTest(said=said):
                self.assertShared(said)

    def test_review_07_a_turn_decided_while_an_answer_is_recorded_never_lends_it_its_flag(self):
        class Racing(VoiceSession):
            """Runs `hook` at the moment an answer is being recorded, as a second thread could."""
            hook = None

            @property
            def _open(self):
                return self.__dict__.get("_open_flag", False)

            @_open.setter
            def _open(self, value):
                self.__dict__["_open_flag"] = value
                hook, self.hook = self.hook, None
                if hook is not None and value is False:
                    hook()

        lookup = "I received a damaged laptop, how do I return it?"
        store = Store()
        session = Racing(Agent("caller", client=store), voice="v")
        first = session.decide(lookup)
        self.assertFalse(first.cacheable)
        session.hook = lambda: session.decide("What are your opening hours?")
        session._record_model_turn(lookup, "Returns are free within 30 days.", turn=first.turn)
        self.assertTrue(all(lookup not in query for query, _, _ in store.writes), store.writes)

        # Recorded in turn order, each answer still keeps its own turn's flag.
        store, session, decisions, _ = call("What are your opening hours?", lookup)
        self.assertEqual(store.writes, [("What are your opening hours?", ANSWER, False)])

    def test_review_09_an_empty_answer_keeps_the_infer_action(self):
        store, session, decisions, _ = call("How long does passport police verification take?", reply="  ")
        decision = decisions[-1]
        self.assertEqual(decision.action, "infer")
        self.assertTrue(decision.needs_model)
        self.assertTrue(decision.empty)
        self.assertFalse(decision.stored)
        self.assertEqual(session.stats()["empty_answers"], 1)
        self.assertEqual(store.writes, [])
        _, _, decisions, _ = call("How long does passport police verification take?")
        self.assertFalse(decisions[-1].empty)
        with self.assertRaises(AttributeError):  # read-only, like needs_model
            decision.empty = False

    def test_review_10_a_story_with_a_personal_detail_never_leaves_the_sdk(self):
        for said in (
            "I ordered a laptop for my wife Priya Sharma, how do I return it?",
            "I received a damaged item for Priya, how do I return it?",
            "I paid 4,999 for it, how do I get a refund?",
            "I bought it for my son, how do I return it?",
        ):
            with self.subTest(said=said):
                store = Store()
                store.shared[said] = "Should never be served."
                decision = session_on(store).decide(said)
                self.assertEqual(decision.action, "infer")
                self.assertEqual(store.reads, [])
                self.assertTrue(_is_personal(said), said)
        said = "I received a damaged laptop, how do I return it?"
        store = Store()
        store.shared[said] = "Damaged items can be returned free within 30 days."
        self.assertEqual(session_on(store).decide(said).action, "serve")
        self.assertEqual(store.reads, [said])

    def test_a_cut_off_question_is_never_served_or_stored(self):
        # The real server served "do you deliver on" the Sundays answer at 0.95 (19 Oct).
        for said in ("do you deliver on", "Can I pay with my", "What is the price of the", "Do you have parking for",
                     "do you deliver on um", "are you open until", "can I return it within"):
            with self.subTest(said=said):
                store = Store()
                store.shared[said] = "Yes, deliveries run on Sundays."
                decision = session_on(store).decide(said)
                self.assertEqual(decision.action, "infer")
                self.assertEqual(store.reads, [])
                self.assertKeptPrivate(said)
        self.assertShared("What happened in 1985?")  # a number ends a finished question
        self.assertShared("How do I log in?")  # the verb takes "in" as its own
        self.assertShared("Do you deliver to Besançon?")
        said = "Do you deliver on Sundays?"
        store = Store()
        store.shared[said] = "Yes, deliveries run on Sundays."
        self.assertEqual(session_on(store).decide(said).action, "serve")
        self.assertShared(said)

    def test_review_11_a_very_long_turn_is_private_and_classified_in_bounded_time(self):
        long_turn = "what are your opening hours on a normal weekday " * 2500  # 22,500 words
        started = time.perf_counter()
        self.assertTrue(_is_personal(long_turn))
        store = Store()
        decision = session_on(store).decide(long_turn)
        self.assertLess(time.perf_counter() - started, 0.5)
        self.assertEqual(decision.action, "infer")
        self.assertFalse(decision.cacheable)
        self.assertEqual(store.reads, [])
        self.assertShared("What are your opening hours on a normal weekday?")

    def test_review_13_where_is_my_nearest_store_stays_private_and_generic_questions_stay_shared(self):
        # Location-dependent: the answer depends on where this caller is.
        self.assertKeptPrivate("Where is my nearest store?")
        self.assertTrue(_is_personal("Where is my nearest store?"))
        for said in (
            "What are your opening hours?",
            "How do I reset a password?",
            "What is the price of the premium plan?",
            "Do you deliver on Sundays?",
            "How do I reset my password?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)


class PipecatReviewFixTests(unittest.TestCase):

    def setUp(self):
        self.pc, self.f, self.Context = _pipecat()
        self.store = Store()
        self.session = session_on(self.store)
        self.answers = []

        async def on_answer(info):
            self.answers.append(info)

        self.gate, self.writeback, _ = self.pc.crowkis_processors(
            self.session, sample_rate=16000, on_answer=on_answer
        )

    async def respond(self, *frames):
        for frame in frames:
            await self.writeback.process_frame(frame, "down")

    def test_review_08_a_tool_call_records_the_answer_after_the_tool_not_an_empty_one(self):
        f = self.f
        question = "When will the parcel arrive?"

        async def with_a_tool():
            await self.gate.process_frame(f.LLMContextFrame(self.Context([user(question)])), "down")
            # The model asks for a tool: no text, then a second response with the real answer.
            await self.respond(f.LLMFullResponseStartFrame(), f.FunctionCallsStartedFrame(),
                               f.FunctionCallInProgressFrame(), f.LLMFullResponseEndFrame())
            await self.respond(f.LLMFullResponseStartFrame(), f.LLMTextFrame("It arrives on Tuesday."),
                               f.LLMFullResponseEndFrame())

        asyncio.run(with_a_tool())
        self.assertEqual([a["answer"] for a in self.answers], ["It arrives on Tuesday."])
        self.assertEqual(self.session.stats()["empty_answers"], 0)
        self.assertEqual(self.session.transcript[-2:], [user(question), {"role": "assistant", "content": "It arrives on Tuesday."}])
        # A tool's result can be this caller's own data: the answer is kept to the call.
        self.assertEqual(self.store.writes, [])
        self.assertFalse(self.answers[-1]["stored"])

        # Without a tool, an answer is recorded and shared as before.
        self.setUp()
        f = self.f  # the frames of the freshly imported processors

        async def plain():
            await self.gate.process_frame(f.LLMContextFrame(self.Context([user("What are your opening hours?")])), "down")
            await self.respond(f.LLMFullResponseStartFrame(), f.LLMTextFrame("Nine to five."), f.LLMFullResponseEndFrame())

        asyncio.run(plain())
        self.assertEqual(self.store.writes, [("What are your opening hours?", "Nine to five.", False)])


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
