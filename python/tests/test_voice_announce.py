"""announce() on a real server: a notice stops a contradicted answer being served (T4).

The withdrawal itself is the server's (decide.rs: "a notice stops what it names being
served at once"); this checks the voice path end to end: a caller's answer is saved and
served to the next caller, the business announces a change, and the next caller is no
longer served the old answer. Needs a real server with the decision engine on:

    CROWKIS_CONFORMANCE_SERVER=1 CROWKIS_HOST=... CROWKIS_TENANT=... python -m pytest tests/test_voice_announce.py
"""
import random
import time
import unittest

import crowkis
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice import _wait_for_writes

from conformance import REAL, _SERVER


def _client():
    settings = {k: (int(v) if k == "port" else v) for k, v in _SERVER.items() if v}
    return crowkis.CrowkisClient(**settings)


def _session(client):
    # No latency budget: a slow lookup must not decide the test either way.
    return crowkis.voice_session(client=client, latency_budget_ms=None)


@unittest.skipUnless(REAL, "needs a real server: CROWKIS_CONFORMANCE_SERVER=1")
class AnnounceTests(unittest.TestCase):
    def test_a_notice_stops_the_answer_it_contradicts_being_served(self):
        client = _client()
        self.addCleanup(client.close)
        # A made-up place, so no earlier run's answer is near it.
        place = "zor" + "".join(random.choice("bcdfghklmnprstvz") + random.choice("aeiou") for _ in range(3))
        question = f"What time does the {place} greenhouse close?"
        if not client.cdecision(question).get("engine"):
            self.skipTest("the server has no decision engine, so it keeps no notices")
        first = _session(client).answer(question, lambda m: f"The {place} greenhouse closes at nine in the evening.")
        _wait_for_writes()
        _wait_for_audio_stores()
        self.assertTrue(first.stored, first.not_stored)
        for _ in range(10):  # a new answer becomes findable within a few seconds
            time.sleep(1)
            if _session(client).decide(question).action == "serve":
                break
        else:
            self.fail("the saved answer was never served to the next caller")

        notice = _session(client).agent.announce(f"the {place} greenhouse closes at 3pm because of the holiday", lasts=60)
        self.addCleanup(client.cnotice_clear, notice["id"])
        time.sleep(0.5)
        later = _session(client).decide(question)
        self.assertNotEqual(later.action, "serve", later.text)


if __name__ == "__main__":
    unittest.main()
