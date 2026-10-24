"""What the voice rules decide for 277 phrases said on their own (T2, 2026-10-21).

fixtures/voice-rule-phrases.json is checked by the Node tests too, so the two
languages cannot drift. A phrase is "never" (never shared), "follow" (cached only with
the turn before it) or "share". A change that moves a phrase towards "share" loosens
privacy: update the fixture only on purpose, with a note."""
import json
import unittest
from pathlib import Path

from crowkis.voice import _is_context_dependent, _is_personal

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "voice-rule-phrases.json").read_text("utf-8"))


def _verdict(phrase: str) -> str:
    return "never" if _is_personal(phrase) else "follow" if _is_context_dependent(phrase) else "share"


class RulePhraseTests(unittest.TestCase):
    def test_every_phrase_gets_its_verdict(self):
        for case in FIXTURE["phrases"]:
            with self.subTest(phrase=case["phrase"], category=case["category"]):
                self.assertEqual(_verdict(case["phrase"]), case["verdict"])

    def test_the_fixture_covers_every_kind(self):
        verdicts = {case["verdict"] for case in FIXTURE["phrases"]}
        self.assertEqual(verdicts, {"never", "follow", "share"})
        self.assertGreaterEqual(len(FIXTURE["phrases"]), 277)


if __name__ == "__main__":
    unittest.main()
