"""v4 P1 review: record() works out the cache key only for an answer, as before the chains."""
import unittest

from test_voice_stress_bugs import Store, session_on


class RecordOrderTests(unittest.TestCase):
    def test_an_empty_answer_is_not_keyed(self):
        session = session_on(Store())
        decision = session.decide("what are your opening hours on weekdays")
        keyed = []
        context_key = session._call.context_key
        session._call.context_key = lambda *args: keyed.append(args) or context_key(*args)
        session.record(decision, "")
        self.assertEqual(keyed, [])

    def test_must_still_work_an_answer_is_keyed_and_saved(self):
        store = Store()
        session = session_on(store)
        session.record(session.decide("what are your opening hours on weekdays"), "Nine to five on weekdays.")
        self.assertEqual([query for query, _, _ in store.writes], ["what are your opening hours on weekdays"])


if __name__ == "__main__":
    unittest.main()
