"""The chat caching report (16 Oct 2026), case by case, through Chat.turn.

The understanding model is scripted with the frames a good model returns, so these tests
check everything after it: what is looked up, what the answering model reads, what is
saved and under which segment. A model that drops a fact, or fails, must keep the turn
private: that is tested too.
"""
import unittest

from crowkis.chat import Chat, ChatConflict, MemoryStore
from crowkis.turn import TurnFrame

GENERAL = {"kind": "general", "subject": "none", "confidence": 0.9}


class SegmentedAgent:
    """A cache keyed by (segment, question), like the server with SEGMENT."""

    def __init__(self):
        self.store, self.asked, self.saved = {}, [], []

    def ask(self, key, segment=None, **kw):
        self.asked.append((segment, key))
        answer = self.store.get((segment, key))
        return {"route": "cache", "answer": answer, "confidence": 0.99} if answer else {"route": "expensive"}

    def learn(self, key, answer, ttl=None, template=False, segment=None):
        self.store[(segment, key)] = answer
        self.saved.append((segment, key, answer, ttl))


class Scripted:
    def __init__(self, frames):
        self.frames = frames

    def understand(self, turn, state):
        frame = self.frames.get(turn)
        if isinstance(frame, Exception):
            raise frame
        return TurnFrame.from_dict(frame)


class Model:
    def __init__(self, reply="Here is the answer."):
        self.reply, self.read = reply, []

    def __call__(self, messages):
        self.read.append(messages)
        return self.reply(messages) if callable(self.reply) else self.reply


def run(frames, turns, agent=None, model=None, **options):
    agent = agent or SegmentedAgent()
    model = model or Model()
    chat = Chat(agent, Scripted(frames), system="You are Acme's assistant.", **options)
    history, replies = [], []
    for turn in turns:
        history.append({"role": "user", "content": turn})
        reply = chat.turn("thread-1", history, answer=model)
        history.append({"role": "assistant", "content": reply.text})
        replies.append(reply)
    return agent, model, replies


def shared_question(model):
    return model.read[-1][-1]["content"]


class ReportCaseTests(unittest.TestCase):
    def test_1_allergy(self):
        frames = {
            "I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9,
                                         "entities": [{"text": "peanut allergy", "type": "condition"}]},
            "Is pad thai safe to eat?": dict(GENERAL, question="Is pad thai safe for someone with a peanut allergy?",
                                             entities=[{"text": "pad thai", "type": "product", "answer_relevant": True}]),
        }
        agent = SegmentedAgent()
        agent.store[("kb=1;lang=und;channel=chat", "Is pad thai safe to eat?")] = "Yes, generally safe."
        agent, model, replies = run(frames, list(frames), agent)
        self.assertNotEqual(replies[-1].text, "Yes, generally safe.")
        self.assertEqual(shared_question(model), "Is pad thai safe for someone with a peanut allergy?")
        self.assertEqual([m["role"] for m in model.read[-1]], ["system", "user"], "the model never reads the chat")
        self.assertEqual(agent.saved[-1][1], "Is pad thai safe for someone with a peanut allergy?")

    def test_1_a_tailored_answer_never_reaches_someone_who_told_nothing(self):
        frames = {
            "I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9,
                                         "entities": [{"text": "peanut allergy", "type": "condition"}]},
            "Is pad thai safe to eat?": dict(GENERAL, question="Is pad thai safe for someone with a peanut allergy?"),
            "Is pad thai safe?": dict(GENERAL, question="Is pad thai safe?"),
        }
        agent = SegmentedAgent()
        chat = Chat(agent, Scripted(frames))
        chat.turn("allergic", [{"role": "user", "content": "I'm allergic to peanuts."}], answer=Model())
        chat.turn("allergic", [{"role": "user", "content": "I'm allergic to peanuts."},
                               {"role": "user", "content": "Is pad thai safe to eat?"}], answer=Model("Avoid it."))
        self.assertTrue(agent.saved[-1][0].startswith("kb=1;lang=und;channel=chat;told="), agent.saved[-1][0])
        plain = chat.turn("plain", [{"role": "user", "content": "Is pad thai safe?"}], answer=Model("Usually, yes."))
        self.assertEqual(agent.asked[-1][0], "kb=1;lang=und;channel=chat", "looked up outside the tailored segment")
        self.assertEqual(plain.text, "Usually, yes.")
        # Another allergic user meets the tailored answer.
        chat.turn("allergic-2", [{"role": "user", "content": "I'm allergic to peanuts."}], answer=Model())
        again = chat.turn("allergic-2", [{"role": "user", "content": "I'm allergic to peanuts."},
                                         {"role": "user", "content": "Is pad thai safe to eat?"}], answer=Model())
        self.assertTrue(again.from_cache)
        self.assertEqual(again.text, "Avoid it.")

    def test_1_a_model_that_drops_the_allergy_keeps_the_turn_private(self):
        frames = {
            "I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9},
            "Is pad thai safe to eat?": dict(GENERAL, question="Is pad thai safe to eat?"),
        }
        agent, model, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "agent")
        self.assertEqual(model.read[-1][0]["content"], "I'm allergic to peanuts.", "the model read the whole chat")
        self.assertEqual(agent.saved, [])
        self.assertEqual(agent.asked, [])

    def test_2_to_5_stated_facts_reach_the_question(self):
        cases = [
            ("My mother has type 2 diabetes.", "What foods should be avoided?",
             "What foods should someone with type 2 diabetes avoid?", "condition", "type 2 diabetes"),
            ("I have a 3 year old daughter.", "What vaccines are due at this age?",
             "What vaccines are due for a 3 year old?", "quantity", "3 year old"),
            ("My son is 12 years old.", "What books should he read?",
             "What books should a 12 year old read?", "quantity", "12 years old"),
            ("I'm planning a trip to Goa in December.", "What should I pack?",
             "What should I pack for a trip to Goa in December?", "place", "Goa in December"),
        ]
        for said, asked, question, etype, text in cases:
            with self.subTest(said=said):
                frames = {said: {"kind": "personal", "subject": "self", "confidence": 0.9,
                                 "entities": [{"text": text, "type": etype}]},
                          asked: dict(GENERAL, question=question)}
                agent, model, replies = run(frames, [said, asked])
                self.assertEqual(shared_question(model), question)
                self.assertEqual(agent.saved[-1][1], question)
                # The statement itself is never shared.
                self.assertTrue(all(s[1] != said for s in agent.saved))

    def test_a_word_the_user_never_said_keeps_the_question_private(self):
        frames = {"My son is 12 years old.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "What books should he read?": dict(GENERAL, question="What books suit a 12 year old?")}
        agent, model, replies = run(frames, list(frames))
        self.assertEqual(agent.saved, [], "'suit' was never said: V6 keeps it private")

    def test_6_language_is_part_of_the_segment(self):
        frames = {
            "Reply only in Hindi from now on.": {"kind": "dialogue", "subject": "none", "confidence": 0.9,
                                                 "language": "hi"},
            "What is the capital of Japan?": dict(GENERAL, question="What is the capital of Japan?", language="hi", entities=[{"text": "Japan", "type": "place"}]),
        }
        agent = SegmentedAgent()
        agent.store[("kb=1;lang=en;channel=chat", "What is the capital of Japan?")] = "The capital of Japan is Tokyo."
        agent, model, replies = run(frames, list(frames), agent, Model("जापान की राजधानी टोक्यो है।"))
        self.assertEqual(replies[-1].text, "जापान की राजधानी टोक्यो है।")
        self.assertIn("Reply in this language: hi.", model.read[-1][1]["content"])
        self.assertEqual(agent.saved[-1][0], "kb=1;lang=hi;channel=chat")

    def test_7_two_hops_resolve_through_the_last_reply(self):
        frames = {
            "What is the capital of France?": dict(GENERAL, question="What is the capital of France?", entities=[{"text": "France", "type": "place"}]),
            "What is its population?": dict(GENERAL, question="What is the population of Paris?", uses_state=True),
            "And how far is it from London?": dict(GENERAL, question="How far is Paris from London?", uses_state=True,
                                                    entities=[{"text": "London", "type": "place"}]),
        }
        model = Model(lambda m: "Paris." if "capital" in m[-1]["content"] else "About 2.1 million.")
        agent, model, replies = run(frames, list(frames), model=model)
        self.assertEqual([s[1] for s in agent.saved],
                         ["What is the capital of France?", "What is the population of Paris?",
                          "How far is Paris from London?"])

    def test_8_an_unresolved_follow_up_stays_private(self):
        frames = {"Compare it with the MacBook Air.": {"kind": "dialogue", "abstain": True, "confidence": 0.3}}
        agent, model, replies = run(frames, list(frames))
        self.assertEqual((agent.saved, agent.asked), ([], []))

    def test_9_steps_again_is_the_earlier_question(self):
        q = "How do I export data to CSV?"
        csv = [{"text": "CSV", "type": "topic"}]
        frames = {"How do I export my data to CSV?": dict(GENERAL, question=q, entities=csv),
                  "What were the steps again?": dict(GENERAL, question=q, uses_state=True)}
        agent, model, replies = run(frames, list(frames), model=Model("Open Data, then Export, then CSV."))
        self.assertTrue(replies[-1].from_cache)
        self.assertEqual(replies[-1].text, "Open Data, then Export, then CSV.")

    def test_10_booking_steps_are_never_shared(self):
        frames = {
            "I want to change my flight.": {"kind": "action", "subject": "self", "confidence": 0.9},
            "The booking reference is K 7 D 9 2 X.": {"kind": "dialogue", "task_step": True, "confidence": 0.9},
            "Mumbai to Bangalore on the 14th.": {"kind": "dialogue", "task_step": True, "confidence": 0.9},
            "Move it to the 16th, evening.": {"kind": "dialogue", "task_step": True, "confidence": 0.9},
        }
        agent, model, replies = run(frames, list(frames))
        self.assertEqual((agent.saved, agent.asked), ([], []))
        self.assertEqual(model.read[-1][0]["content"], "I want to change my flight.")


class SafetyTests(unittest.TestCase):
    def test_every_understanding_failure_keeps_the_turn_private(self):
        turn = "What is your refund policy?"
        for frame in (RuntimeError("model down"), None, {"kind": "general", "confidence": 0.2,
                                                           "question": turn}, {"abstain": True}):
            with self.subTest(frame=frame):
                agent, model, replies = run({turn: frame}, [turn])
                self.assertEqual((agent.saved, agent.asked), ([], []))
                self.assertEqual(replies[0].text, "Here is the answer.")

    def test_a_word_from_a_private_turn_is_never_in_a_shared_answer(self):
        frames = {"Hi, my name is Sarah and my order is 55512.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "What is your refund policy?": dict(GENERAL, question="What is your refund policy?")}
        agent, model, replies = run(frames, list(frames), model=Model("Sarah, refunds take 30 days."))
        self.assertEqual(agent.saved, [])
        self.assertEqual(replies[-1].outcome, "refused:private_word")

    def test_an_emergency_gets_the_business_script_and_nothing_is_kept(self):
        frames = {"My child swallowed bleach, what do I do?": dict(GENERAL, question="What to do if a child swallows bleach?")}
        agent, model, replies = run(frames, list(frames), urgent_reply="Call 112 now. Poison helpline: 1800-116-117.")
        self.assertEqual(replies[0].text, "Call 112 now. Poison helpline: 1800-116-117.")
        self.assertEqual((agent.saved, agent.asked, model.read), ([], [], []))

    def test_the_businesss_tools_answer_personal_and_live_turns(self):
        frames = {"What is my balance?": {"kind": "live", "subject": "self", "confidence": 0.9}}
        agent, model, replies = run(frames, list(frames), on_tools=lambda turn, frame: "Your balance is ₹2,400.")
        self.assertEqual(replies[0].text, "Your balance is ₹2,400.")
        self.assertEqual((agent.saved, model.read), ([], []))

    def test_expiry_follows_the_question_type(self):
        frames = {"Find hotels in Pune": dict(GENERAL, question="What hotels are in Pune?", question_type="search", entities=[{"text": "Pune", "type": "place"}]),
                  "What is your refund policy?": dict(GENERAL, question="What is your refund policy?", question_type="policy")}
        agent, _, _ = run(frames, list(frames))
        self.assertEqual([s[3] for s in agent.saved], [3600, None])


class ThreadMemoryTests(unittest.TestCase):
    def test_a_fact_said_in_one_request_counts_in_the_next(self):
        # run() makes one Chat.turn per request: the allergy crossed requests through the store.
        frames = {"I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "Is pad thai safe to eat?": dict(GENERAL, question="Is pad thai safe to eat?")}
        agent, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "agent")

    def test_two_requests_on_one_thread_cannot_overwrite_each_other(self):
        class Racing(MemoryStore):
            def load(self, thread_id):
                data, version = super().load(thread_id)
                super().save(thread_id, data or {}, version)  # another request saved meanwhile
                return data, version

        frames = {"Hello": {"kind": "chitchat", "confidence": 0.9}}
        chat = Chat(SegmentedAgent(), Scripted(frames), store=Racing())
        with self.assertRaises(ChatConflict):
            chat.turn("t", [{"role": "user", "content": "Hello"}], answer=Model())

    def test_damaged_memory_starts_a_fresh_thread(self):
        store = MemoryStore()
        store.save("t", {"state": "garbage", "next_turn": "x"}, 0)
        frames = {"What is your refund policy?": dict(GENERAL, question="What is your refund policy?")}
        chat = Chat(SegmentedAgent(), Scripted(frames), store=store)
        reply = chat.turn("t", [{"role": "user", "content": "What is your refund policy?"}], answer=Model())
        self.assertEqual(reply.outcome, "saved")

    def test_threads_are_kept_apart(self):
        frames = {"I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "Is pad thai safe to eat?": dict(GENERAL, question="Is pad thai safe to eat?")}
        agent = SegmentedAgent()
        chat = Chat(agent, Scripted(frames))
        chat.turn("a", [{"role": "user", "content": "I'm allergic to peanuts."}], answer=Model())
        reply = chat.turn("b", [{"role": "user", "content": "Is pad thai safe to eat?"}], answer=Model())
        self.assertEqual(reply.outcome, "saved", "another thread's allergy never reaches this one")


class ReviewFindingTests(unittest.TestCase):
    def test_a_language_asked_for_once_stays_when_later_turns_are_in_english(self):
        frames = {"Reply only in Hindi from now on.": {"kind": "dialogue", "confidence": 0.9, "language": "hi"},
                  "What is the capital of Japan?": dict(GENERAL, question="What is the capital of Japan?", language="en", entities=[{"text": "Japan", "type": "place"}])}
        agent, model, _ = run(frames, list(frames))
        self.assertEqual(agent.saved[-1][0], "kb=1;lang=hi;channel=chat")
        self.assertIn("Reply in this language: hi.", model.read[-1][1]["content"])

    def test_a_language_is_only_ever_a_language_tag(self):
        for raw in ("en;told=1", "hindi (devanagari) please", "en;region=goa", "x" * 40):
            self.assertIsNone(TurnFrame.from_dict({"language": raw}).language, raw)
        self.assertEqual(TurnFrame.from_dict({"language": "pt-BR"}).language, "pt-br")

    def test_a_segment_value_cannot_add_a_field(self):
        from crowkis.verify import RuleChecker
        segment = RuleChecker().build_segment({"region": "goa;told=1", "segment": "a=b"}, "hi")
        self.assertEqual(segment, "kb=1;lang=hi;region=goa_told_1;segment=a_b;channel=chat")

    def test_a_fact_in_the_first_question_itself_tailors_it(self):
        q = "Is pad thai safe for someone with a peanut allergy?"
        frames = {q: dict(GENERAL, question=q, entities=[{"text": "peanut allergy", "type": "condition"}])}
        agent, _, _ = run(frames, [q])
        self.assertIn(";told=", agent.saved[-1][0])

    def test_peanut_and_shellfish_answers_never_meet(self):
        def asked(fact):
            q = f"Is pad thai safe for someone with a {fact} allergy?"
            frames = {f"I'm allergic to {fact}.": {"kind": "personal", "subject": "self", "confidence": 0.9,
                                                   "entities": [{"text": f"{fact} allergy", "type": "condition"}]},
                      "Is pad thai safe to eat?": dict(GENERAL, question=q)}
            agent, _, _ = run(frames, list(frames))
            return agent.saved[-1][0]
        self.assertNotEqual(asked("peanut"), asked("shellfish"))
        self.assertEqual(asked("peanut"), asked("peanut"), "two peanut-allergic users share")

    def test_one_fact_said_two_ways_meets_the_same_answers(self):
        def asked(said, question):
            frames = {said: {"kind": "personal", "subject": "self", "confidence": 0.9},
                      "Is pad thai safe to eat?": dict(GENERAL, question=question)}
            agent, _, _ = run(frames, list(frames))
            return agent.saved[-1][0]
        q = "Is pad thai safe for someone with a peanut allergy?"
        self.assertEqual(asked("I'm allergic to peanuts.", q), asked("I have a peanut allergy.", q))
        q = "Is pad thai safe to eat for someone with diabetes?"
        self.assertEqual(asked("I'm diabetic.", q), asked("I have diabetes.", q))
        # Must still work: different facts never meet.
        self.assertNotEqual(asked("I have diabetes.", q),
                            asked("I have a peanut allergy.", "Is pad thai safe for someone with a peanut allergy?"))

    def test_an_information_question_is_neither_an_emergency_nor_a_fact_about_the_user(self):
        q = "What are the symptoms of a heart attack?"
        frames = {q: dict(GENERAL, question=q), "What is your refund policy?": dict(GENERAL, question="What is your refund policy?")}
        agent, _, replies = run(frames, list(frames), urgent_reply="Call 112.")
        self.assertEqual(replies[0].route, "shared")
        self.assertEqual(replies[1].outcome, "saved", "the rest of the chat is still shared")

    def test_damaged_saved_memory_never_breaks_a_thread(self):
        q = "What is your refund policy?"
        for damaged in ({"state": {"attributes": [1, 2]}}, {"state": {"facts": 5, "private_words": 7, "stated": "abc"}},
                        {"next_turn": float("inf")}, {"state": None}, "garbage", {"state": {"stated": [1, None, {}]}}):
            with self.subTest(damaged=damaged):
                store = MemoryStore()
                store.save("t", damaged, 0)
                chat = Chat(SegmentedAgent(), Scripted({q: dict(GENERAL, question=q)}), store=store)
                self.assertEqual(chat.turn("t", [{"role": "user", "content": q}], answer=Model()).outcome, "saved")

    def test_content_parts_and_any_thread_id(self):
        q = "What is your refund policy?"
        chat = Chat(SegmentedAgent(), Scripted({q: dict(GENERAL, question=q)}))
        reply = chat.turn(42, [{"role": "user", "content": [{"type": "text", "text": q}]}], answer=Model())
        self.assertEqual(reply.outcome, "saved")

    def test_unrelated_threads_do_not_wait_for_each_other(self):
        import threading
        import time
        q = "What is your refund policy?"
        chat = Chat(SegmentedAgent(), Scripted({q: dict(GENERAL, question=q)}))

        def slow(messages):
            time.sleep(0.4)
            return "Refunds take 30 days."

        started = time.perf_counter()
        workers = [threading.Thread(target=chat.turn, args=(f"t{n}", [{"role": "user", "content": q}], slow)) for n in range(4)]
        [w.start() for w in workers]
        [w.join() for w in workers]
        self.assertLess(time.perf_counter() - started, 1.2, "four threads ran one after another")
        self.assertEqual(chat._locks, {}, "no lock is kept once its turn is done")

    def test_a_one_word_fact_is_kept_and_carried(self):
        for fact, turn, question in (("I'm diabetic.", "What foods should I avoid?", "What foods should someone who is diabetic avoid?"),
                                     ("I'm vegan.", "What can I cook tonight?", "What can a vegan cook tonight?")):
            frames = {fact: {"kind": "personal", "subject": "self", "confidence": 0.9},
                      turn: dict(GENERAL, question=question)}
            _, _, replies = run(frames, list(frames))
            self.assertEqual((replies[-1].route, replies[-1].outcome), ("shared", "saved"), fact)
        # Deliberate: a later question that does not carry the fact stays private (fixed code
        # cannot tell it is unrelated), so a dropped fact costs a hit, never a wrong answer.
        frames = {"I'm diabetic.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "How do I reset a password?": dict(GENERAL, question="How do I reset a password?")}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "agent")

    def test_what_the_question_already_says_does_not_split_the_cache(self):
        france = {"region": {"value": "France", "normalised": "france", "changes_answer": True}}
        frames = {"What is the capital of France?": dict(GENERAL, question="What is the capital of France?", attributes=france,
                                                         entities=[{"text": "France", "type": "place"}]),
                  "Which city is the capital of France?": dict(GENERAL, question="Which city is the capital of France?",
                                                               entities=[{"text": "France", "type": "place"}])}
        agent, _, _ = run(frames, list(frames), model=Model("The capital of France is Paris."))
        self.assertEqual([seg for seg, *_ in agent.saved], ["kb=1;lang=und;channel=chat"] * 2)
        # Must still work: a region the question does not say is the user's own and stays in the key.
        frames = {"Which laptops are in stock?": dict(GENERAL, question="Which laptops are in stock?", attributes={
            "region": {"value": "Pune", "normalised": "pune", "changes_answer": True}})}
        agent, _, _ = run(frames, list(frames))
        self.assertEqual(agent.saved[0][0], "kb=1;lang=und;region=pune;channel=chat")

    def test_this_is_marks_a_name_not_an_ordinary_word(self):
        frames = {"This is the third time my order is late.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "How do I track an order?": dict(GENERAL, question="How do I track an order?")}
        _, _, replies = run(frames, list(frames), model=Model("Open the orders page and pick the order."))
        self.assertEqual(replies[-1].outcome, "saved")

    def test_a_thread_memory_stays_small_whatever_is_said_or_restored(self):
        huge = "I'm allergic to " + "peanuts " * 50_000
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({}), store=store)
        for n in range(3):
            chat.turn("t", [{"role": "user", "content": huge}], answer=Model("x " * 50_000))
        self.assertLess(len(str(store.load("t")[0])), 40_000)
        from crowkis.callstate import CallState
        restored = CallState.from_dict({"stated": [huge] * 50, "last_reply": huge, "active_question": huge})
        self.assertLess(len(str(restored.to_dict())), 40_000)

    def test_memory_keeps_no_name_from_a_private_reply(self):
        said = "Where is my order?"
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({said: {"kind": "personal", "subject": "self", "confidence": 0.9}}), store=store)
        chat.turn("t", [{"role": "user", "content": said}],
                  answer=Model("Sarah, order 555123 ships to sarah@example.com on Friday. Anything else?"))
        kept = store.load("t")[0]["state"]["last_reply"]
        for private in ("sarah", "555123", "example"):
            self.assertNotIn(private, kept.lower())
        self.assertTrue(kept.endswith("?"), kept)

    def test_a_lowercase_name_is_private_too(self):
        frames = {"hi i'm sarah, where is my order?": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "What is your refund policy?": dict(GENERAL, question="What is your refund policy?")}
        _, _, replies = run(frames, list(frames), model=Model("Sarah, refunds take 5 days."))
        self.assertEqual(replies[-1].outcome, "refused:private_word")

    def test_a_question_with_a_private_word_is_never_shared(self):
        frames = {"my name is sarah, where is my order?": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "Is pad thai spicy for sarah?": dict(GENERAL, question="Is pad thai spicy for sarah?")}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "agent")
        # Must still work: a number the user told as a fact (an age) is carried on purpose.
        frames = {"I have a 3 year old daughter.": {"kind": "personal", "subject": "self", "confidence": 0.9},
                  "What vaccines are due at this age?": dict(GENERAL, question="What vaccines are due at age 3?")}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "shared")

    def test_a_generic_word_alone_does_not_carry_a_specific_fact(self):
        said = "I'm allergic to penicillin."
        for question, route in (("What can someone with allergies take for a sore throat?", "agent"),
                                ("What can someone allergic to penicillin take for a sore throat?", "shared")):
            frames = {said: {"kind": "personal", "subject": "self", "confidence": 0.9},
                      "What can I take for a sore throat?": dict(GENERAL, question=question)}
            _, _, replies = run(frames, list(frames))
            self.assertEqual(replies[-1].route, route, question)

    def test_names_in_any_script_are_masked_in_a_private_reply(self):
        said = "Where is my order?"
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({said: {"kind": "personal", "subject": "self", "confidence": 0.9}}), store=store)
        chat.turn("t", [{"role": "user", "content": said}], answer=Model("Émile, Дмитрий and 王伟 will call you."))
        kept = store.load("t")[0]["state"]["last_reply"]
        for name in ("Émile", "Дмитрий", "王伟"):
            self.assertNotIn(name, kept)

    def test_only_a_region_the_question_says_word_for_word_leaves_the_key(self):
        frames = {"Do you sell Jordans?": dict(GENERAL, question="Do you sell Jordans?", entities=[{"text": "Jordans", "type": "product"}], attributes={
            "region": {"value": "Jordan", "normalised": "jordan", "changes_answer": True}})}
        agent, _, _ = run(frames, list(frames))
        self.assertEqual(agent.saved[0][0], "kb=1;lang=und;region=jordan;channel=chat")
        # The place the question names keeps it apart by itself, however the model wrote the region.
        frames = {"What should I pack for Goa?": dict(GENERAL, question="What should I pack for Goa?", entities=[{"text": "Goa", "type": "place"}], attributes={
            "region": {"value": "Goa, India", "normalised": "goa, india", "changes_answer": True}})}
        agent, _, _ = run(frames, list(frames))
        self.assertEqual(agent.saved[0][0], "kb=1;lang=und;channel=chat")

    def test_memory_counts_characters_and_digits_the_same_in_every_sdk(self):
        from crowkis.callstate import CallState
        self.assertEqual(len(CallState.from_dict({"last_reply": "\U0001F600" * 1500}).last_reply), 1000)
        said = "I have a \u0967\u0968 year old son."
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({said: {"kind": "personal", "subject": "self", "confidence": 0.9}}), store=store)
        chat.turn("t", [{"role": "user", "content": said}], answer=Model())
        self.assertIn("\u0967\u0968", store.load("t")[0]["state"]["stated"][0])

    def test_a_reply_says_why_it_was_not_shared(self):
        frames = {"I'm allergic to peanuts.": {"kind": "personal", "subject": "self", "confidence": 0.9}}
        _, _, replies = run(frames, list(frames))
        self.assertIn("V3_not_general", replies[-1].reason)

    def test_every_detail_of_a_stated_fact_reaches_the_question(self):
        said = "I'm planning a trip to Goa in December."
        for question, route in (("What should I pack for a trip to Goa?", "agent"),
                                ("What should I pack for a trip to Goa in December?", "shared")):
            frames = {said: {"kind": "personal", "subject": "self", "confidence": 0.9,
                             "entities": [{"text": "Goa", "type": "place"}]},
                      "What should I pack?": dict(GENERAL, question=question)}
            _, _, replies = run(frames, list(frames))
            self.assertEqual(replies[-1].route, route, question)
        # A name is not a detail the question must carry, and the memory keeps no detail as text.
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({"I'm Sarah and I'm allergic to peanuts.": {
            "kind": "personal", "subject": "self", "confidence": 0.9}}), store=store)
        chat.turn("t", [{"role": "user", "content": "I'm Sarah and I'm allergic to peanuts."}], answer=Model())
        self.assertNotIn("sarah", str(store.load("t")[0]).lower())

    def test_review3_names_details_lists_regions(self):
        def last(frames, model=None):
            _, _, replies = run(frames, list(frames), model=model)
            return replies[-1]
        PERSONAL = {"kind": "personal", "subject": "self", "confidence": 0.9}
        # 1. A name given in a turn that is itself shared is never in its answer, nor in a later question.
        frames = {"Hi, I'm Sarah. What is the refund policy?": dict(GENERAL, question="What is the refund policy?"),
                  "Is pad thai spicy for sarah?": dict(GENERAL, question="Is pad thai spicy for sarah?")}
        _, _, replies = run(frames, list(frames), model=Model("Sarah, refunds take 5 days."))
        self.assertEqual(replies[0].outcome, "refused:private_word")
        self.assertEqual(replies[1].route, "agent")
        said = "I'm Sarah and I'm allergic to peanuts. What snacks are safe?"
        self.assertEqual(last({said: dict(GENERAL, question="What snacks are safe for Sarah who is allergic to peanuts?")}).route, "agent")
        # 2. A name opening a sentence.
        self.assertEqual(last({"Priya and I are allergic to nuts.": PERSONAL,
                               "What snacks are safe?": dict(GENERAL, question="What snacks are safe for Priya who is allergic to nuts?")}).route, "agent")
        # 3. A place the model did not tag keeps the chat private: it is never dropped from the question.
        for question in ("What should I pack for a trip in December?", "What should I pack for a trip to Goa in December?"):
            self.assertEqual(last({"I'm planning a trip to Goa in December.": PERSONAL,
                                   "What should I pack?": dict(GENERAL, question=question)}).route, "agent", question)
        # 4. Every item of a list the user told is carried.
        fact = "I'm allergic to penicillin and peanuts."
        for question, route in (("Which antibiotics can someone allergic to peanuts take?", "agent"),
                                ("Which antibiotics can someone allergic to penicillin and peanuts take?", "shared")):
            self.assertEqual(last({fact: PERSONAL, "Which antibiotics can I take?": dict(GENERAL, question=question)}).route, route, question)
        # 5. A region is dropped only when the question names all of it.
        new_york = {"region": {"value": "New York", "normalised": "new york", "changes_answer": True}}
        agent, _, _ = run({"What new phones are in stock?": dict(GENERAL, question="What new phones are in stock?", attributes=new_york)},
                          ["What new phones are in stock?"])
        self.assertEqual(agent.saved[0][0], "kb=1;lang=und;region=new york;channel=chat")
        # A number told in digits is carried by its word.
        self.assertEqual(last({"I have a 3 year old daughter.": PERSONAL,
                               "What vaccines are due at this age?": dict(GENERAL, question="What vaccines are due for a three year old?")}).route, "shared")

    def test_review4_names_in_the_question(self):
        PERSONAL = {"kind": "personal", "subject": "self", "confidence": 0.9}
        def last(frames):
            _, _, replies = run(frames, list(frames))
            return replies[-1]
        # A capitalised word in a shared question must be something the model tagged as a place,
        # thing or topic, a month or day, or a word of the chat's earlier shared turns.
        self.assertEqual(last({"My son Arjun is 12.": PERSONAL,
                               "Books for him?": dict(GENERAL, question="What books are good for Arjun who is 12?")}).route, "agent")
        self.assertEqual(last({"Can you help my colleague Priya with returns?": dict(
            GENERAL, question="How do returns work for Priya?")}).route, "agent")
        france = [{"text": "France", "type": "place"}]
        self.assertEqual(last({"What is the capital of France?": dict(
            GENERAL, question="What is the capital of France?", entities=france)}).route, "shared")
        self.assertEqual(last({"What is the capital of France?": dict(
            GENERAL, question="What is the capital of France?", entities=france),
            "What is its population?": dict(GENERAL, question="What is the population of France?")}).route, "shared")
        # A lowercase name given with a fact ("i'm sarah and ...") is a name.
        self.assertEqual(last({"i'm sarah and i'm allergic to peanuts": PERSONAL,
                               "What snacks are safe?": dict(GENERAL, question="What snacks are safe for sarah who is allergic to peanuts?")}).route, "agent")
        # Any shape of name the model did not tag: all capitals, mixed case, a sentence's first word, a script
        # without capitals. An acronym the model tagged is shared.
        for question in ("How do returns work for PRIYA?", "Can McKenzie return items?", "Priya can return items how?",
                         "How do returns work for \u738b\u4f1f?"):
            self.assertEqual(last({"Returns?": dict(GENERAL, question=question)}).route, "agent", question)
        self.assertEqual(last({"How do I enable SSO?": dict(GENERAL, question="How do I enable SSO?",
                                                             entities=[{"text": "SSO", "type": "topic"}])}).route, "shared")
        # "and I ..." starts a new clause, not a list: the allergy question is still shared.
        self.assertEqual(last({"I'm allergic to peanuts and I live alone.": PERSONAL,
                               "Is pad thai safe?": dict(GENERAL, question="Is pad thai safe for someone allergic to peanuts?")}).route, "shared")

    def test_a_rewrite_may_add_a_question_word_never_a_fact(self):
        PERSONAL = {"kind": "personal", "subject": "self", "confidence": 0.9}
        def last(frames):
            _, _, replies = run(frames, list(frames))
            return replies[-1]
        # A word that could change what is asked ("avoid" for "good with", "cheapest", "safe") is never added.
        self.assertEqual(last({"Which foods are good with gout?": dict(GENERAL, question="Which foods should someone with gout avoid?")}).route, "agent")
        self.assertEqual(last({"What hotels are in Paris?": dict(GENERAL, question="What are the cheapest hotels in Paris?",
                                                                 entities=[{"text": "Paris", "type": "place"}])}).route, "agent")
        # Exact words only: "tim" is not "time".
        self.assertEqual(last({"Order 4 for tim, status?": {"kind": "personal", "subject": "other", "confidence": 0.9},
                               "How long do refunds take?": dict(GENERAL, question="How long do refunds take for tim?")}).route, "agent")
        self.assertEqual(last({"How many people live in Paris?": dict(GENERAL, question="What is the population of Paris?",
                                                                      entities=[{"text": "Paris", "type": "place"}])}).route, "shared")
        # Must still work: a word that would tailor the answer, never said, keeps it private.
        self.assertEqual(last({"What should I cook tonight?": dict(GENERAL, question="What should a vegan cook tonight?")}).route, "agent")

    def test_a_name_after_a_relation_is_a_name_whatever_the_model_says(self):
        frames = {"My colleague JOSE needs a refund.": {"kind": "personal", "subject": "other", "confidence": 0.9,
                                                       "entities": [{"text": "JOSE", "type": "product"}]},
                  "How long do refunds take?": dict(GENERAL, question="How long do refunds take for JOSE?",
                                                    entities=[{"text": "JOSE", "type": "product"}])}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "agent")
        for said, name in (("My teacher Mr Smith asked about refunds.", "Smith"), ("My friend O'Brien wants a refund.", "Brien"),
                           ("My wife's sister PRIYA needs a refund.", "PRIYA"), ("My son's teacher Ms RAO needs a refund.", "RAO")):
            wrong_tag = [{"text": name, "type": "product"}]  # the model mis-tags the name; fixed code must not
            frames = {said: {"kind": "personal", "subject": "other", "confidence": 0.9, "entities": wrong_tag},
                      "How long do refunds take?": dict(GENERAL, question=f"How long do refunds take for {name}?", entities=wrong_tag)}
            _, _, replies = run(frames, list(frames))
            self.assertEqual(replies[-1].route, "agent", said)
        # Must still work: a product or team name after a relation-like word is not a person.
        frames = {"Is Customer Support open on Sunday?": dict(GENERAL, question="Is Customer Support open on Sunday?",
                                                               entities=[{"text": "Customer Support", "type": "topic"}])}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "shared")

    def test_a_non_answer_to_the_question_alone_is_answered_from_the_whole_chat(self):
        frames = {"How do I reset my password?": dict(GENERAL, question="How do I reset a password?"),
                  "What were the steps again?": dict(GENERAL, question="What were the steps again?", uses_state=True)}
        def model(messages):
            if len(messages) <= 2 and "again" in messages[-1]["content"]:
                return "I don't have access to your previous conversation history, so I cannot recall the steps."
            return "Click Forgot password, then follow the emailed link."
        agent, _, replies = run(frames, list(frames), model=Model(model))
        self.assertEqual(replies[-1].text, "Click Forgot password, then follow the emailed link.")
        self.assertEqual(replies[-1].outcome, "refused:non_answer")
        self.assertEqual([s[1] for s in agent.saved], ["How do I reset a password?"])
        # The thread remembers the reply the user saw, not the discarded one.
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted(frames), store=store)
        history = []
        for turn in frames:
            history.append({"role": "user", "content": turn})
            history.append({"role": "assistant", "content": chat.turn("t", history, answer=Model(model)).text})
        self.assertNotIn("access", store.load("t")[0]["state"]["last_reply"])

    def test_an_unresolved_follow_up_is_never_shared(self):
        france = [{"text": "France", "type": "place"}]
        london = [{"text": "London", "type": "place"}]
        for said, question, tags in (("And how far is it from London?", "How far is it from London?", london),
                                     # a neutral question word added does not resolve the reference
                                     ("How many people live there?", "What is the population there?", []),
                                     ("How far is it from London?", "What is the distance from it to London?", london),
                                     ("Is that one open on Sundays?", "Is it open on Sundays?", []),
                                     ("How much does that cost?", "How much does that cost?", []),
                                     ("How long does this take?", "How long does this take?", []),
                                     # a contraction's "s" names nothing; a dropped reference is not resolved
                                     ("How many people live there?", "What's the population there?", []),
                                     ("Who is their president?", "Who is the president?", []),
                                     ("Is that one open on Sundays?", "Is one open on Sundays?", [])):
            frames = {"What's the capital of France?": dict(GENERAL, question="What's the capital of France?", entities=france),
                      said: dict(GENERAL, question=question, uses_state=True, entities=tags)}
            agent, _, replies = run(frames, list(frames), model=Model("Paris is about 340 km from London."))
            self.assertEqual(replies[-1].route, "agent", question)
            frames = {"What is the capital of France?": dict(GENERAL, question="What is the capital of France?", entities=france),
                      said: dict(GENERAL, question=question, uses_state=True, entities=tags)}
            agent, _, replies = run(frames, list(frames), model=Model("Paris is about 340 km from London."))
            self.assertEqual(replies[-1].route, "agent", question)
            self.assertEqual([s[1] for s in agent.saved], ["What is the capital of France?"], question)

    def test_a_resolved_follow_up_keeps_its_filler_word(self):
        for said, question, place in (("Is it safe to eat pad thai there?", "Is it safe to eat pad thai in Thailand?", "Thailand"),
                                      ("What is there to do there?", "What is there to do in Paris?", "Paris"),
                                      ("And what time is it there?", "What time is it in Tokyo?", "Tokyo")):
            tag = [{"text": place, "type": "place"}]
            frames = {f"Tell me about {place}.": dict(GENERAL, question=f"Tell me about {place}.", entities=tag),
                      said: dict(GENERAL, question=question, uses_state=True, entities=tag)}
            _, _, replies = run(frames, list(frames))
            self.assertEqual(replies[-1].route, "shared", question)
        # A question that stands alone is shared when the model does not lean on the chat.
        frames = {"Is it raining in Paris?": dict(GENERAL, question="Is it raining in Paris?",
                                                  entities=[{"text": "Paris", "type": "place"}])}
        _, _, replies = run(frames, list(frames))
        self.assertEqual(replies[-1].route, "shared")

    def test_a_reply_that_cannot_determine_is_a_non_answer(self):
        from crowkis.voice import _is_non_answer
        # A hedged real answer is an answer.
        self.assertFalse(_is_non_answer("I can't determine the exact date, but historians place it around 1200 BC."))
        for text in ("I cannot determine your location, but you can check Google Maps.",
                     "I cannot determine that, but I recommend checking online.",
                     "I can't determine that, but please ask a local guide.",
                     "I couldn't determine that.", "I could not determine the distance.",
                     "It is impossible to determine that.", "It's impossible to determine without your city."):
            self.assertTrue(_is_non_answer(text), text)
        # A reply that cannot answer ("I cannot determine ...") is a non-answer: never saved.
        frames = {"How far is London?": dict(GENERAL, question="How far is London?", entities=[{"text": "London", "type": "place"}])}
        _, _, replies = run(frames, list(frames), model=Model(
            "I cannot determine the distance from London without knowing your current location. Please provide your city."))
        self.assertEqual(replies[-1].outcome, "refused:non_answer")

    def test_memory_keeps_no_email(self):
        said = "I'm allergic to peanuts, email me at sarah@example.com"
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted({said: {"kind": "personal", "subject": "self", "confidence": 0.9}}), store=store)
        chat.turn("t", [{"role": "user", "content": said}], answer=Model())
        saved = str(store.load("t")[0]).lower()
        self.assertNotIn("sarah", saved)
        self.assertIn("allergic", saved)

    def test_memory_keeps_no_name_or_long_number_and_can_be_forgotten(self):
        frames = {"Hi, I'm Sarah, my order 55512 arrived damaged.": {"kind": "personal", "subject": "self", "confidence": 0.9}}
        store = MemoryStore()
        chat = Chat(SegmentedAgent(), Scripted(frames), store=store)
        chat.turn("t", [{"role": "user", "content": "Hi, I'm Sarah, my order 55512 arrived damaged."}], answer=Model())
        saved = str(store.load("t")[0])
        self.assertNotIn("sarah", saved.lower())
        self.assertNotIn("55512", saved)
        chat.forget("t")
        self.assertEqual(store.load("t"), (None, 0))


if __name__ == "__main__":
    unittest.main()
