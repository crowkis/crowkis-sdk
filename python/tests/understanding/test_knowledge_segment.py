"""One pool per tenant: every channel, with or without an understander, looks up and saves in kb=<version>,
so a new knowledge version is a deliberate new pool."""
import unittest

from crowkis import VoiceSession
from crowkis.client.agent import Agent
from crowkis.keys import KnowledgeSegment
from crowkis.understanding.slots import WordRuleClassifier


class SegmentedStore:
    """A cache whose answers live per segment; it records what each call sent."""

    def __init__(self):
        self.answers = {}
        self.sent = []

    def cget_hit(self, query, **kwargs):
        self.sent.append(("get", kwargs.get("segment")))
        found = self.answers.get((kwargs.get("segment"), query))
        if found is None:
            return None
        from crowkis import CacheHit
        return CacheHit(response=found.encode(), similarity=0.99, ttl_remaining=600, matched_key=b"k",
                        confidence=0.99, hit_type="semantic")

    def cset(self, query, response, **kwargs):
        self.sent.append(("set", kwargs.get("segment")))
        self.answers[(kwargs.get("segment"), query)] = response

    def ctoolget(self, *args, **kwargs):
        return None

    def ctoolset(self, *args, **kwargs):
        return None

    def close(self):
        pass


def session_on(store, **options):
    return VoiceSession(Agent("caller", client=store), voice="v", **options)


def save(store, **options):
    session = session_on(store, **options)
    session.record(session.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.")


class KnowledgeSegmentTests(unittest.TestCase):
    def test_every_lookup_and_save_carries_the_version_with_an_understander(self):
        store = SegmentedStore()
        save(store, classifier=WordRuleClassifier())
        self.assertEqual(set(store.sent), {("get", "kb=1"), ("set", "kb=1")})

    def test_a_new_version_does_not_meet_the_old_answers(self):
        store = SegmentedStore()
        save(store, classifier=WordRuleClassifier())
        same = session_on(store, classifier=WordRuleClassifier()).decide("what are your opening hours on sunday")
        self.assertEqual(same.action, "serve")
        newer = session_on(store, classifier=WordRuleClassifier(), knowledge_version="2")
        self.assertEqual(newer.decide("what are your opening hours on sunday").action, "infer")

    def test_the_same_segment_without_an_understander(self):
        store = SegmentedStore()
        save(store)
        self.assertEqual(set(store.sent), {("get", "kb=1"), ("set", "kb=1")})

    def test_voice_and_chat_share_one_pool_in_both_modes(self):
        for options in ({}, {"classifier": WordRuleClassifier()}):
            store = SegmentedStore()
            voice = session_on(store, **options)
            voice.record(voice.decide("what are your opening hours on sunday"), "We open at 10 on Sundays.")
            chat = session_on(store, channel="chat", **options)
            self.assertEqual(chat.decide("what are your opening hours on sunday").action, "serve")

    def test_the_segment_cannot_be_broken(self):
        self.assertEqual(KnowledgeSegment("2").segment, "kb=2")
        self.assertEqual(KnowledgeSegment("v1;x=y").segment, "kb=v1_x_y")


class VoiceStatedFactsTests(unittest.TestCase):
    QUESTION = "what are your opening hours on sunday"

    def test_must_still_work_voice_with_stated_facts_does_not_share(self):
        session = session_on(SegmentedStore(), classifier=WordRuleClassifier())
        self.assertIsNotNone(session.decide(self.QUESTION).messages)
        session.decide("i am allergic to peanuts")
        self.assertIsNone(session.decide(self.QUESTION).messages)


if __name__ == "__main__":
    unittest.main()
