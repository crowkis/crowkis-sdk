"""v4 P5 item 5: with an understander, voice answers live in kb=<version>;channel=<name>, so switching
understanders or knowledge is a deliberate new version. Without one, nothing is sent (as before)."""
import unittest

from crowkis import VoiceSession
from crowkis.agent import Agent
from crowkis.keys import KnowledgeSegment
from crowkis.turns.channel import REALTIME, VOICE
from crowkis.understanding.word_rule_classifier import WordRuleClassifier


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
        self.assertEqual(set(store.sent), {("get", "kb=1;channel=voice"), ("set", "kb=1;channel=voice")})

    def test_a_new_version_does_not_meet_the_old_answers(self):
        store = SegmentedStore()
        save(store, classifier=WordRuleClassifier())
        same = session_on(store, classifier=WordRuleClassifier()).decide("what are your opening hours on sunday")
        self.assertEqual(same.action, "serve")
        newer = session_on(store, classifier=WordRuleClassifier(), knowledge_version="2")
        self.assertEqual(newer.decide("what are your opening hours on sunday").action, "infer")

    def test_must_still_work_without_an_understander_no_segment_is_sent(self):
        store = SegmentedStore()
        save(store)
        self.assertEqual(set(store.sent), {("get", None), ("set", None)})

    def test_the_segment_names_the_channel_and_cannot_be_broken(self):
        self.assertEqual(KnowledgeSegment("2", REALTIME).segment, "kb=2;channel=realtime")
        self.assertEqual(KnowledgeSegment("v1;x=y", VOICE).segment, "kb=v1_x_y;channel=voice")


if __name__ == "__main__":
    unittest.main()
