"""F8 step 2: chat runs on the voice front end. ``voice_session(channel="chat")`` (one session per thread)
and ``voice_session()`` (a call) share one pool on one tenant, without and with a classifier and rewriter."""
import threading
import time
import unittest

from crowkis import CacheHit, voice_session
from crowkis.client.agent import Agent
from crowkis.understanding.model.understanders import ReplayRewriter
from crowkis.understanding.slots import WordRuleClassifier

HOURS = "what are your opening hours on sunday"
HOURS_ANSWER = "We open at 10 on Sundays."
TABLE = "| day | hours |\n| --- | --- |\n| sun | 10 |"
PLANS = "which plans do you offer"


class Tenant:
    """One tenant's cache: exact matches per segment, shared by every session; ``delay`` slows a lookup."""

    def __init__(self, delay=0.0):
        self.answers = {}
        self.writes = []
        self.delay = delay
        self.tenant = None

    def cget_hit(self, query, **kwargs):
        time.sleep(self.delay)
        found = self.answers.get((kwargs.get("segment"), query))
        if found is None:
            return None
        return CacheHit(response=found.encode(), similarity=0.99, ttl_remaining=600, matched_key=b"k",
                        confidence=0.99, hit_type="exact")

    def cset(self, query, response, **kwargs):
        self.writes.append((kwargs.get("segment"), query, response))
        self.answers[(kwargs.get("segment"), query)] = response

    def ctoolget(self, *args, **kwargs):
        return None

    def ctoolset(self, *args, **kwargs):
        return None

    def close(self):
        pass


def understood():
    return {"classifier": WordRuleClassifier(), "rewriter": ReplayRewriter({HOURS: HOURS})}


def chat(tenant, **options):
    return voice_session(client=tenant, channel="chat", **options)


def call(tenant, **options):
    return voice_session(voice="v", client=tenant, **options)


def say(session, text, answer):
    decision = session.decide(text)
    if decision.needs_model:
        session.record(decision, answer)
    return decision


def ask_model(session, text):
    """A model that repeats everything it was sent: the question alone, or the whole call."""
    decision = session.decide(text)
    if decision.needs_model:
        seen = decision.messages or [{"content": turn["content"]} for turn in session.transcript]
        session.record(decision, "Noted: " + " / ".join(m["content"] for m in seen))
    return decision


class ChatOnVoiceTests:
    options = {}

    def test_a_general_answer_saved_on_chat_is_served_on_voice(self):
        tenant = Tenant()
        say(chat(tenant, **self.options), HOURS, HOURS_ANSWER)
        heard = call(tenant, **self.options).decide(HOURS)
        self.assertEqual((heard.action, heard.text), ("serve", HOURS_ANSWER))

    def test_and_the_reverse(self):
        tenant = Tenant()
        say(call(tenant, **self.options), HOURS, HOURS_ANSWER)
        read = chat(tenant, **self.options).decide(HOURS)
        self.assertEqual((read.action, read.text), ("serve", HOURS_ANSWER))

    def test_a_screen_only_answer_saved_on_chat_is_served_on_chat_not_on_voice(self):
        tenant = Tenant()
        say(chat(tenant, **self.options), PLANS, TABLE)
        self.assertEqual(chat(tenant, **self.options).decide(PLANS).text, TABLE)
        spoken = call(tenant, **self.options).decide(PLANS)
        self.assertEqual((spoken.action, spoken.rule), ("infer", "ScreenOnlyAnswer"))

    def test_the_chat_lookup_budget_is_one_second_and_voice_keeps_250_ms(self):
        tenant = Tenant(delay=0.5)
        say(chat(tenant, **self.options), HOURS, HOURS_ANSWER)
        self.assertEqual(chat(tenant, **self.options).latency_budget_ms, 1000)
        self.assertEqual(chat(tenant, **self.options).decide(HOURS).action, "serve")
        self.assertEqual(call(tenant, **self.options).decide(HOURS).action, "infer")

    def test_a_detail_stated_in_one_thread_never_reaches_the_other_channel(self):
        for sender, receiver in ((chat, call), (call, chat)):
            tenant = Tenant()
            thread = sender(tenant, **self.options)
            thread.decide("my name is Priya Sharma and my order number is 48213")
            ask_model(thread, HOURS)
            ask_model(thread, "where is my order 48213")
            stored = repr(tenant.writes).lower()
            for secret in ("priya", "48213"):
                self.assertNotIn(secret, stored)
            other = receiver(tenant, **self.options)
            self.assertEqual(other.decide("where is my order 48213").action, "infer")
            # What the other channel is served about a general question holds nothing the thread said.
            served = other.decide(HOURS).text or ""
            for secret in ("priya", "48213"):
                self.assertNotIn(secret, served.lower())

    def test_a_stated_condition_never_reaches_the_other_channel(self):
        tenant = Tenant()
        thread = chat(tenant, **self.options)
        thread.decide("i am allergic to peanuts")
        ask_model(thread, HOURS)
        self.assertNotIn("peanuts", repr(tenant.writes).lower())
        self.assertEqual(call(tenant, **self.options).decide(HOURS).action, "infer")


class WithoutUnderstanderTests(ChatOnVoiceTests, unittest.TestCase):
    options = {}


class WithClassifierAndRewriterTests(ChatOnVoiceTests, unittest.TestCase):
    @property
    def options(self):
        return understood()


class ChatProtectionsOnVoiceTests(unittest.TestCase):
    """What Chat kept private that the voice word rules shared (v4-notes/f8-chat-replay.md): both channels."""

    NAMES_A_PERSON = ["What did Priya order last week?", "Has Sarah paid yet?",
                      "asks Anita about the refund policy", "Is the manager named Rahul in today?"]
    NAMES_NO_ONE = ["Do you ship to Australia?", "Is there a discount for Diwali?", "What is the capital of France?",
                    "Can I pay with Apple Pay?", "Is the store open on Sunday?", "Are there flights for Goa?"]
    URLS = ["what is on https://shop.example.com/track?id=abc", "is www.shop.example.com/x safe to open"]

    def sessions(self):
        for make in (call, chat):
            yield make(Tenant())

    def test_a_question_naming_a_person_is_not_shared(self):
        for text in self.NAMES_A_PERSON:
            for session in self.sessions():
                self.assertIsNone(session.decide(text).messages, text)

    def test_must_still_work_a_question_naming_no_one_is_shared(self):
        for text in self.NAMES_NO_ONE:
            for session in self.sessions():
                self.assertIsNotNone(session.decide(text).messages, text)

    def test_a_question_holding_a_link_is_not_shared(self):
        for text in self.URLS:
            for session in self.sessions():
                self.assertIsNone(session.decide(text).messages, text)

    def test_a_name_the_caller_gave_never_reaches_a_shared_answer_whatever_the_model_knows(self):
        for make in (call, chat):
            tenant = Tenant()
            thread = make(tenant)
            thread.decide("this is Priya Sharma, my phone is 9876543210")
            say(thread, HOURS, "Hello Priya Sharma, we open at 10 on Sundays.")
            self.assertNotIn("priya", repr(tenant.writes).lower())
            self.assertEqual(make(tenant).decide(HOURS).action, "infer")

    def test_must_still_work_a_clean_answer_after_a_private_turn_is_saved(self):
        tenant = Tenant()
        thread = chat(tenant)
        thread.decide("this is Priya Sharma, my phone is 9876543210")
        say(thread, HOURS, HOURS_ANSWER)
        self.assertEqual(call(tenant).decide(HOURS).text, HOURS_ANSWER)


if __name__ == "__main__":
    unittest.main()
