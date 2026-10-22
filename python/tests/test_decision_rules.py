"""v4 P0: every voice decision names the rule that made it (fixtures/decision-rules.json).

`decision.rule` is the question or hit rule behind decide()'s action and `decision.save_rule`
the save rule behind record()'s outcome. Both are added fields: action, reason, stored and
not_stored are unchanged. node/test-decision-rules.js checks the same fixture."""
import json
import unittest
from pathlib import Path

from test_voice_stress_bugs import Store, session_on

FIXTURE = json.loads((Path(__file__).resolve().parents[2] / "fixtures" / "decision-rules.json").read_text("utf-8"))


def _last_decision(case):
    store = Store(refuse=RuntimeError("write refused") if case.get("refuse") else None)
    session = session_on(store, **case.get("options", {}))
    last = len(case["turns"]) - 1
    for index, (said, reply) in enumerate(zip(case["turns"], case["replies"])):
        decision = session.decide(said)
        if decision.needs_model:
            decision = session.record(decision, reply, private=bool(case.get("private")) and index == last)
    return decision


class DecisionRuleTests(unittest.TestCase):
    def test_every_decision_names_its_rules(self):
        for case in FIXTURE["cases"]:
            with self.subTest(case=case["name"]):
                decision = _last_decision(case)
                self.assertEqual(decision.action, case.get("action", "infer"))
                self.assertEqual(decision.rule, case["rule"])
                self.assertEqual(decision.save_rule, case["save_rule"])

    def test_a_new_decision_names_no_rule_yet(self):
        decision = session_on(Store()).decide("what is your refund policy")
        self.assertIsNone(decision.save_rule)

    def test_a_turn_talked_over_is_interrupted(self):
        session = session_on(Store())
        decision = session.decide("what is your refund policy")
        session.cancel()
        decision = session.record(decision, "Refunds take five business days.")
        self.assertEqual(decision.save_rule, "Interrupted")

    def test_the_hit_guards_are_named(self):
        store = Store()
        store.shared["what is your refund policy"] = "See https://example.com/refunds for details."
        decision = session_on(store).decide("what is your refund policy")
        self.assertEqual((decision.action, decision.rule), ("infer", "ScreenOnlyAnswer"))

    def test_an_unreachable_cache_is_named(self):
        store = Store()
        store.cget_hit = lambda *args, **kwargs: (_ for _ in ()).throw(ConnectionError("down"))
        decision = session_on(store).decide("what is your refund policy")
        self.assertEqual(decision.rule, "CacheUnavailable")


if __name__ == "__main__":
    unittest.main()
