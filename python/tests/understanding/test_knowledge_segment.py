"""v4 P5 item 5: with an understander, voice answers live in kb=<version>;channel=<name>, so switching
understanders or knowledge is a deliberate new version. Without one, nothing is sent (as before)."""
import unittest

from crowkis import VoiceSession
from crowkis.client.agent import Agent
from crowkis.keys import KnowledgeSegment
from crowkis.rules.rule_checker import RuleChecker
from crowkis.turns.values import REALTIME, VOICE
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


class VoiceAndChatShareOneKeyBuilderTests(unittest.TestCase):
    """Full segments differ by lang= and told= (voice has neither); kb= and channel= and the key do not."""

    QUESTION = "what are your opening hours on sunday"

    def test_the_same_question_gets_the_same_key_and_segment_fields(self):
        session = session_on(SegmentedStore(), classifier=WordRuleClassifier())
        chat = RuleChecker(channel="voice")
        self.assertEqual(session._call.context_key(self.QUESTION, self.QUESTION), chat.build_key(self.QUESTION, {}))
        chat_fields = [f for f in chat.build_segment({}, "en").split(";") if not f.startswith("lang=")]
        self.assertEqual(session._segment.split(";"), chat_fields)

    def test_must_still_work_voice_with_stated_facts_does_not_share(self):
        session = session_on(SegmentedStore(), classifier=WordRuleClassifier())
        self.assertIsNotNone(session.decide(self.QUESTION).messages)
        session.decide("i am allergic to peanuts")
        self.assertIsNone(session.decide(self.QUESTION).messages)


if __name__ == "__main__":
    unittest.main()
