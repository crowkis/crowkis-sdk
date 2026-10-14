"""One test per bug from the voice stress test (100 calls, 13 Oct 2026).

"Saved" in the report means an answer was written to the shared cache, where it
can be served to other callers. Each test runs the report's own example plus
close variants through the path a user takes (VoiceSession.answer, or the
Pipecat processors), with a fake client standing in for the server.
"""

import asyncio
import logging
import sys
import threading
import types
import unittest
from unittest import mock

from crowkis.agent import Agent
from crowkis.client import CacheHit, CrowkisError
from crowkis.voice import VoiceSession, _is_context_dependent, _is_personal

ANSWER = "Here is the answer."


class Store:
    """The server: a shared store and a template store, matched on the exact key."""

    def __init__(self, refuse=None):
        self.shared = {}
        self.templates = {}
        self.reads = []
        self.writes = []
        self.refuse = refuse

    def cget_hit(self, query, **kwargs):
        self.reads.append(query)
        found = (self.templates if kwargs.get("template") else self.shared).get(query)
        if found is None:
            return None
        return CacheHit(
            response=found.encode(), similarity=0.99, ttl_remaining=600,
            matched_key=b"k", confidence=0.99, hit_type="semantic",
        )

    def cset(self, query, response, *, ttl=None, tenant=None, template=False):
        if self.refuse is not None:
            raise self.refuse
        self.writes.append((query, response, template))
        (self.templates if template else self.shared)[query] = response

    def ctoolget(self, tool, args_str, *, tenant=None):
        return None

    def ctoolset(self, tool, args_str, result, *, ex=None, tenant=None):
        return None

    def close(self):
        return None


def session_on(store, **kwargs):
    return VoiceSession(Agent("caller", client=store), voice="v", **kwargs)


def call(*turns, reply=ANSWER, store=None, **kwargs):
    """Run one call through VoiceSession.answer; returns the store, session,
    each turn's decision, and the messages the model read on each model turn.
    The model says `reply` to the last turn and ANSWER to the ones before it."""
    store = store if store is not None else Store()
    session = session_on(store, **kwargs)
    seen, decisions = [], []

    for index, said in enumerate(turns):
        said_last = reply if index == len(turns) - 1 else ANSWER
        decisions.append(session.answer(said, lambda messages: seen.append(messages) or said_last))
    return store, session, decisions, seen


def user(text):
    return {"role": "user", "content": text}


class StressBugTests(unittest.TestCase):

    def assertKeptPrivate(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertFalse(decisions[-1].cacheable, said)
        self.assertTrue(all(said not in query for query, _, _ in store.writes), (said, store.writes))
        self.assertTrue(_is_personal(said), said)

    def assertShared(self, said, *before):
        store, _, decisions, _ = call(*before, said)
        self.assertTrue(decisions[-1].cacheable, said)
        self.assertIn((said, ANSWER, False), store.writes, said)
        self.assertFalse(_is_personal(said), said)

    def assertModelSawTheCall(self, turns):
        """The last turn is answered with the whole call in view, and nothing of it is stored."""
        store, _, decisions, seen = call(*turns)
        last = decisions[-1]
        self.assertIsNone(last.messages, turns)
        self.assertFalse(last.cacheable, turns)
        self.assertEqual(seen[-1][0], user(turns[0]), turns)
        self.assertEqual(seen[-1][-1], user(turns[-1]), turns)
        self.assertTrue(all(turns[-1] not in query for query, _, _ in store.writes), turns)

    # --- Rules that let private things be shared ----------------------------------------

    def test_bug_01_a_name_said_about_anyone_is_private(self):
        for said in (
            "His name was Suresh Pillai.",
            "Her name is Anita Desai.",
            "The account holder's name is Ramesh Kumar.",
            "I'm calling about a patient named Suresh.",
            "It's for Mr Pillai.",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)

    def test_bug_02_spaced_digits_and_spoken_ids_are_private(self):
        for said in (
            "His account number ends in 4 4 0 9.",
            "Is 4 4 0 9 correct?",
            "Is double four zero nine right?",
            "Is 4 four 0 nine right?",
            "Is 98 765 43 the right one?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
        # A price or a weight is not an identifier.
        self.assertShared("Is the 1,499 plan good for families?")
        self.assertShared("How much is a 2 kg parcel to Delhi?")

    def test_bug_03_his_her_their_details_are_private(self):
        for said in (
            "Can you tell me her test results?",
            "When is her appointment?",
            "What is his account balance?",
            "Did their refund go through?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)

    def test_bug_04_my_anything_is_private(self):
        for said in (
            "Where is my food?",
            "Has my calendar synced?",
            "Is our table ready?",
            "When does my flight leave?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
        # A how-to that mentions "my" is still general.
        self.assertShared("How can I improve my sleep?")

    def test_bug_05_can_i_get_my_thing_is_a_request_not_a_how_to(self):
        for said in (
            "Can I get a refill of my prescription?",
            "Could I get a copy of my statement?",
            "Can I have my bill split in two?",
            "Can we book our usual table for Friday?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
        self.assertShared("Can I change the address on my account?")

    def test_bug_06_a_confirmation_is_a_reply_not_a_question(self):
        for said in (
            "Fine, book it.",
            "Alright, do it.",
            "Perfect, confirm the booking.",
            "Sounds good, book it.",
            "Okay, go ahead with that.",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said, "Do you have a table for two at 8 pm?")
        self.assertShared("Okay, can I return shoes?")

    def test_bug_07_a_command_is_private(self):
        for said in (
            "Set a timer for 10 minutes.",
            "Remind me to call mom at 6.",
            "Turn off the bedroom lights.",
            "Please set an alarm for 7 am.",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)
        self.assertShared("Explain how ordering works.")

    def test_bug_08_a_life_event_is_private(self):
        for said in (
            "I lost my job, I can't pay this month.",
            "I was laid off last week and can't afford the bill.",
            "We just had a baby so money is tight.",
            "My husband passed away last month.",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)

    def test_bug_09_a_question_about_this_call_reads_the_call(self):
        for turns in (
            ("Add milk and eggs to the shopping list.", "What did I ask you to add to the shopping list?"),
            ("Do you have this shirt in medium and large?", "Which size did I pick earlier?"),
            ("How long does shipping take to Pune?", "What was the first thing I asked?"),
            ("Does the phone come with a warranty?", "Can you repeat what you said about the warranty?"),
        ):
            with self.subTest(turns=turns):
                self.assertModelSawTheCall(turns)
                self.assertTrue(_is_personal(turns[-1]))

    # --- Context lost, so the model answered blind --------------------------------------

    def test_bug_10_a_follow_up_with_no_content_of_its_own_reads_the_question_before_it(self):
        for said in ("Which is cheaper?", "What's the difference?", "Which is faster?", "Which would you recommend?"):
            with self.subTest(said=said):
                store, _, decisions, seen = call("What plans do you have?", said)
                self.assertEqual(seen[-1], [user("What plans do you have?"), user(said)])
                self.assertTrue(decisions[-1].cacheable)
                self.assertEqual(store.writes[-1][0], f"What plans do you have? || {said}")
                self.assertTrue(_is_context_dependent(said))

    def test_bug_11_an_emergency_follow_up_keeps_the_emergency(self):
        for turns in (
            ("My father collapsed!", "What do I do?"),
            ("My child swallowed a battery.", "What should I do now?"),
            ("My wife fainted and is not responding.", "Help, what now?"),
        ):
            with self.subTest(turns=turns):
                self.assertModelSawTheCall(turns)

    def test_bug_12_hinglish_aur_is_a_follow_up(self):
        first = "What do I get in the 199 plan?"
        for said in ("Aur 299 wale mein?", "aur 499 wala?", "Aur yearly plan mein kitna?", "Phir monthly wala?"):
            with self.subTest(said=said):
                store, _, decisions, seen = call(first, said)
                self.assertEqual(seen[-1], [user(first), user(said)])
                self.assertTrue(decisions[-1].cacheable)
                self.assertEqual(store.writes[-1][0], f"{first} || {said}")

    def test_bug_13_a_chain_of_follow_ups_stays_as_private_as_its_first_turn(self):
        for turns in (
            ("Book a table", "For four people", "At 8 pm tomorrow"),
            ("I want to book a table", "for four people", "and at 8 pm tomorrow"),
            ("Reschedule my appointment", "to next week", "in the morning please"),
        ):
            with self.subTest(turns=turns):
                store, _, decisions, seen = call(*turns)
                self.assertEqual(store.writes, [])
                self.assertFalse(decisions[-1].cacheable)
                self.assertIsNone(decisions[-1].messages)
                self.assertEqual(seen[-1][0], user(turns[0]))
        # A general chain is shared, keyed and answered with every turn in it.
        turns = ("What does the pro plan cost?", "And for ten people?", "And for twenty?")
        store, _, decisions, seen = call(*turns)
        self.assertEqual(seen[-1], [user(t) for t in turns])
        self.assertEqual(store.writes[-1][0], " || ".join(turns))

    # --- Rules too strict: each must now be shareable -----------------------------------

    def test_bug_14_for_a_kind_of_customer_inside_a_question_is_general(self):
        for said in (
            "What is the grace period for premium payment?",
            "Is there a discount for senior citizens?",
            "What benefits are there for employees?",
            "What perks are available for gold members?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)
        for said in (
            "What is the grace period for my premium payment?",
            "For business accounts, what is the refund policy?",
            "As a senior, what discount do I get?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)

    def test_bug_15_a_sensitive_word_alone_does_not_make_a_question_personal(self):
        for said in (
            "What should I bring to a first consultation with a lawyer?",
            "What does a family lawyer usually charge?",
            "Is legal aid available for small claims?",
            "What does a doctor check in a routine physical?",
        ):
            with self.subTest(said=said):
                self.assertShared(said)
        for said in (
            "My lawyer says I should sue, should I?",
            "I am pregnant, can I take this medicine?",
            "Should I see a doctor about my chest pain?",
            "Is this cream safe during pregnancy?",
        ):
            with self.subTest(said=said):
                self.assertKeptPrivate(said)

    def test_bug_16_a_how_to_after_a_personal_story_is_served_from_cache_and_never_stored(self):
        for said in (
            "Hello, I received a damaged product. How do I return it?",
            "I ordered a jacket and it is too small, how do I exchange it?",
            "I bought a phone case but it does not fit, can I return it?",
            "I was charged twice, what should I do?",
        ):
            with self.subTest(said=said):
                warm = Store()
                warm.shared[said] = "Damaged or unwanted items can be returned free within 30 days."
                served = session_on(warm).decide(said)
                self.assertEqual(served.action, "serve")
                self.assertEqual(served.text, "Damaged or unwanted items can be returned free within 30 days.")

                store, _, decisions, _ = call(said)
                self.assertEqual(store.writes, [])
                self.assertFalse(decisions[-1].cacheable)
        # The story alone, or with an identifier, is never even looked up.
        for said in (
            "I received a damaged product, order 55512. How do I return it?",
            "I received a damaged product yesterday.",
        ):
            with self.subTest(said=said):
                store = Store()
                store.shared[said] = "Should never be served."
                self.assertEqual(session_on(store).decide(said).action, "infer")
                self.assertEqual(store.reads, [])

    def test_bug_17_an_it_that_points_forward_is_not_a_follow_up(self):
        for said in (
            "What does it cost to send a 2 kg parcel?",
            "How long does it take to deliver to Pune?",
            "Is it possible to change a booking date?",
            "How much does it cost to ship a parcel abroad?",
        ):
            with self.subTest(said=said):
                self.assertFalse(_is_context_dependent(said))
                self.assertShared(said)
                self.assertShared(said, "What are your opening hours?")
        for said in ("How long does it take?", "Is it refundable to the original card?"):
            with self.subTest(said=said):
                self.assertTrue(_is_context_dependent(said))

    # --- SDK -------------------------------------------------------------------------------

    def test_bug_21_any_script_the_rules_cannot_read_is_private(self):
        for said in (
            "என் அப்பாயின்ட்மென்ட் எப்போது?",
            "আমার অ্যাপয়েন্টমেন্ট কখন?",
            "నా అపాయింట్‌మెంట్ ఎప్పుడు?",
            "मेरा ऑर्डर कब आएगा?",
            "Когда мой заказ?",
            "What is the status of मेरा order?",
        ):
            with self.subTest(said=said):
                store = Store()
                store.shared[said] = "Delivery takes three days."
                decision = session_on(store).decide(said)
                self.assertEqual(decision.action, "infer")
                self.assertFalse(decision.cacheable)
                self.assertEqual(store.reads, [])
                self.assertTrue(_is_personal(said))
        self.assertShared("Is the café open on Sundays?")

    def test_bug_24_an_interrupted_or_earlier_answer_is_never_stored_or_attached(self):
        store = Store()
        session = session_on(store)
        entered, release = threading.Event(), threading.Event()

        def slow(messages):
            entered.set()
            release.wait(5)
            return "Travel insurance covers medical costs abroad."

        first = threading.Thread(
            target=session.answer, args=("Does the premium plan include travel insurance?", slow)
        )
        first.start()
        self.assertTrue(entered.wait(5))
        self.assertTrue(session.cancel())  # the caller talks over the model
        session.answer("What are your opening hours?", lambda m: "We are open nine to five.")
        release.set()
        first.join(5)
        self.assertEqual(store.writes, [("What are your opening hours?", "We are open nine to five.", False)])
        self.assertNotIn("Travel insurance covers medical costs abroad.", str(session.transcript))

        # A turn's answer recorded after a newer turn was decided belongs to the old turn.
        store = Store()
        session = session_on(store)
        old = session.decide("What are your opening hours?")
        session.decide("What is the refund policy?")
        session._record_model_turn("What is the refund policy?", "We are open nine to five.", turn=old.turn)
        self.assertEqual(store.writes, [])
        self.assertEqual(session.transcript, [])

    def test_bug_25_an_empty_answer_is_never_stored_and_is_reported(self):
        for reply in ("", "   \n ", None):
            with self.subTest(reply=reply):
                store, session, decisions, _ = call(
                    "How long does passport police verification take?", reply=reply
                )
                self.assertEqual(store.writes, [])
                self.assertEqual(decisions[-1].action, "infer")
                self.assertTrue(decisions[-1].empty)
                self.assertFalse(decisions[-1].stored)
                self.assertIn("empty", decisions[-1].not_stored)
                self.assertEqual(session.stats()["empty_answers"], 1)
                self.assertEqual(session.transcript, [])

    def test_bug_26_a_refused_write_carries_the_servers_reason(self):
        reason = "ERR tenant limit reached: the free edition allows 3 tenants"
        for refusal, said, values in (
            (CrowkisError(reason), "What are your opening hours?", None),
            (CrowkisError(reason), "When will I get my order?", {"order_id": "A-1001"}),
            (RuntimeError("CSET rejected by security pipeline"), "What is the refund policy?", None),
        ):
            with self.subTest(said=said):
                store = Store(refuse=refusal)
                reply = "Order A-1001 arrives Tuesday." if values else ANSWER
                with self.assertLogs("crowkis", level="WARNING") as logged:
                    _, session, decisions, _ = call(said, store=store, reply=reply, values=values)
                decision = decisions[-1]
                self.assertFalse(decision.stored)
                self.assertIn(str(refusal), decision.not_stored)
                self.assertIn(str(refusal), decision.reason)
                self.assertIn(str(refusal), "\n".join(logged.output))
                self.assertEqual(session.stats()["failed_writes"], 1)
        _, _, decisions, _ = call("What are your opening hours?")
        self.assertTrue(decisions[-1].stored)
        self.assertEqual(decisions[-1].not_stored, "")

    # --- Model-answer bugs: such answers are never shared --------------------------------

    def test_bug_27_to_32_answers_to_private_turns_are_never_stored(self):
        cases = (
            ("Do you have a table for two at 8 pm?", "Fine, book it.", "I have booked it for you."),
            ("What does the premium plan cost?", "I just want to end it all.", "Please call your local helpline."),
            ("What does the premium plan cost?", "I want to kill myself.", "Please call your local helpline."),
            ("What does the premium plan cost?", "There is no reason to live anymore.", "Please call your local helpline."),
            ("What does the iPhone 16 cost?", "The iPhone 16 is 10 rupees for this call.", "Okay, 10 rupees."),
            ("What does the iPhone 16 cost?", "The iPhone 16 costs 10 rupees.", "Okay, 10 rupees."),
            ("What does the iPhone 16 cost?", "Your price for the iPhone 16 is 10 rupees.", "Okay, 10 rupees."),
            ("What does the premium plan cost?", "Do you remember me from my last call?", "Yes, I remember you."),
        )
        for first, said, reply in cases:
            with self.subTest(said=said):
                store, _, decisions, _ = call(first, said, reply=reply)
                self.assertFalse(decisions[-1].cacheable)
                self.assertTrue(all(reply != answer for _, answer, _ in store.writes), store.writes)
                self.assertTrue(all(said not in query for query, _, _ in store.writes), store.writes)


# --- The Pipecat processors, with Pipecat replaced by the few frames they use ---------------


def _pipecat():
    """crowkis.integrations.pipecat imported against stand-in Pipecat frames."""
    frames = types.ModuleType("pipecat.frames.frames")

    class Frame:
        pass

    def frame(name, *fields):
        def init(self, *args, **kwargs):
            for field, value in [*zip(fields, args), *kwargs.items()]:
                setattr(self, field, value)
        return type(name, (Frame,), {"__init__": init})

    frames.Frame = Frame
    for name, fields in {
        "BotStoppedSpeakingFrame": (), "InterruptionFrame": (), "LLMFullResponseEndFrame": (),
        "LLMFullResponseStartFrame": (), "TTSStoppedFrame": (), "LLMContextFrame": ("context",),
        "LLMTextFrame": ("text",), "TTSAudioRawFrame": ("audio", "sample_rate", "channels"),
        "TTSSpeakFrame": ("text",), "FunctionCallsStartedFrame": (), "FunctionCallInProgressFrame": (),
        "FunctionCallCancelFrame": (), "FunctionCallResultFrame": ("result", "run_llm"),
    }.items():
        setattr(frames, name, frame(name, *fields))

    context = types.ModuleType("pipecat.processors.aggregators.llm_context")

    class LLMContext:
        def __init__(self, messages=None):
            self.messages = list(messages or [])

        def add_message(self, message):
            self.messages.append(message)

    context.LLMContext = LLMContext

    processor = types.ModuleType("pipecat.processors.frame_processor")

    class FrameProcessor:
        def __init__(self):
            self.pushed = []

        async def process_frame(self, frame, direction):
            return None

        async def push_frame(self, frame, direction=None):
            self.pushed.append(frame)

    processor.FrameProcessor = FrameProcessor
    processor.FrameDirection = types.SimpleNamespace(DOWNSTREAM="down", UPSTREAM="up")

    stubs = {
        "pipecat": types.ModuleType("pipecat"),
        "pipecat.frames": types.ModuleType("pipecat.frames"),
        "pipecat.frames.frames": frames,
        "pipecat.processors": types.ModuleType("pipecat.processors"),
        "pipecat.processors.aggregators": types.ModuleType("pipecat.processors.aggregators"),
        "pipecat.processors.aggregators.llm_context": context,
        "pipecat.processors.frame_processor": processor,
    }
    with mock.patch.dict(sys.modules, stubs):
        sys.modules.pop("crowkis.integrations.pipecat", None)
        import crowkis.integrations.pipecat as integration
    return integration, frames, LLMContext


class PipecatStressBugTests(unittest.TestCase):

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

    def ask(self, *said):
        return self.gate.process_frame(
            self.f.LLMContextFrame(self.Context([user(s) for s in said])), "down"
        )

    async def respond(self, text, end=True):
        await self.writeback.process_frame(self.f.LLMFullResponseStartFrame(), "down")
        await self.writeback.process_frame(self.f.LLMTextFrame(text), "down")
        if end:
            await self.writeback.process_frame(self.f.LLMFullResponseEndFrame(), "down")

    def test_bug_24_the_models_leftover_answer_never_lands_on_the_callers_next_words(self):
        insurance = "Yes, the premium plan includes travel insurance."
        question = "Does the premium plan include travel insurance?"

        async def talked_over_mid_answer():
            await self.ask(question)
            await self.respond(insurance, end=False)
            await self.ask(question, "Okay, never mind.")
            await self.writeback.process_frame(self.f.LLMFullResponseEndFrame(), "down")

        asyncio.run(talked_over_mid_answer())
        self.assertEqual(self.store.writes, [])

        async def asked_again_before_the_model_started():
            await self.ask("What are your opening hours?")
            await self.respond(insurance)
            await self.respond("We are open nine to five.")

        self.setUp()
        asyncio.run(self.ask(question))
        asyncio.run(asked_again_before_the_model_started())
        self.assertEqual(self.store.writes, [("What are your opening hours?", "We are open nine to five.", False)])

        async def interrupted():
            await self.ask(question)
            await self.respond(insurance, end=False)
            interruption = self.f.InterruptionFrame()
            await self.gate.process_frame(interruption, "down")
            await self.writeback.process_frame(interruption, "down")
            await self.ask("What are your opening hours?")
            await self.writeback.process_frame(self.f.LLMFullResponseEndFrame(), "down")

        self.setUp()
        asyncio.run(interrupted())
        self.assertEqual(self.store.writes, [])

    def test_bug_25_and_26_the_answer_callback_says_what_was_not_stored_and_why(self):
        async def silent():
            await self.ask("How long does passport police verification take?")
            await self.respond("   ")

        asyncio.run(silent())
        self.assertEqual(self.store.writes, [])
        self.assertFalse(self.answers[-1]["stored"])
        self.assertIn("empty", self.answers[-1]["not_stored"])
        self.assertEqual(self.session.stats()["empty_answers"], 1)

        reason = "ERR tenant limit reached: the free edition allows 3 tenants"
        self.store.refuse = CrowkisError(reason)

        async def refused():
            await self.ask("What are your opening hours?")
            await self.respond("We are open nine to five.")

        with self.assertLogs("crowkis", level="WARNING"):
            asyncio.run(refused())
        self.assertFalse(self.answers[-1]["stored"])
        self.assertIn(reason, self.answers[-1]["not_stored"])


if __name__ == "__main__":
    logging.basicConfig()
    unittest.main()
