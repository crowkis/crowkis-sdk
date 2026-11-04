"""v4 P1: each question, hit and save rule alone, on a fake call (fixtures/rules/<stage>/<Rule>.json,
shared with Node)."""
import json
import time
import unittest
from pathlib import Path

from crowkis.rules import hit, question, save
from crowkis.state.call_state import CallState
from crowkis.understanding.turn_frame import TurnFrame
from crowkis.turns.values import CachedAnswer
from crowkis.turns.voice.turn import ModelAnswer, VoiceTurn
from crowkis.turns.chat.turn import ChatAnswer
from crowkis.turns.values import CHAT, REALTIME, VOICE
from crowkis.turns.chat.turn import ChatTurn
from crowkis.turns.values import Hit
from crowkis.rules.rule_checker import Verdict as ChatVerdict
from crowkis.understanding.frame_reading import FrameReading
from crowkis.understanding.word_rule_classifier import WordRuleClassifier

from fake_call import FakeCall

RULE_FILES = sorted((Path(__file__).resolve().parents[3] / "fixtures" / "rules").glob("*/*.json"))
CASES = [dict(case, rule=data["rule"], stage=data["stage"], subject=data.get("subject", "voice"))
         for data in (json.loads(path.read_text("utf-8")) for path in RULE_FILES) for case in data["cases"]]
CHANNELS = {"voice": VOICE, "chat": CHAT, "realtime": REALTIME}
RULES = {name: getattr(stage, name) for stage in (question, hit, save) for name in stage.__all__}


def subject(case, call):
    if case["subject"] == "chat_answer":
        frame = TurnFrame.from_dict(case["frame"]) if "frame" in case else None
        return ChatAnswer(" ".join(case["answer"].split()), ChatVerdict(True, "shared", [], **case["verdict"]), frame,
                          CallState.from_dict(case["state"]), instructions=case["instructions"],
                          prompt_key=(None, None, "chat"), private=case.get("private", False))
    if case["subject"] == "chat":
        return ChatTurn(TurnFrame.from_dict(case["frame"]), case["say"], CallState.from_dict(case["state"]))
    # A case with a frame is read by a model (v4); without one, by the word rules.
    reading = (FrameReading(TurnFrame.from_dict(case["frame"])) if "frame" in case
               else WordRuleClassifier().classify(case["say"].strip()))
    turn = VoiceTurn(case["say"], call, reading)
    if case["stage"] == "question":
        return turn
    if case["stage"] == "hit":
        return CachedAnswer(turn, Hit.from_agent(case["hit"]), time.monotonic())
    return ModelAnswer(case["say"], case["answer"], call.key, call, private=case.get("private", False),
                       instructions=case.get("instructions"), cacheable=case.get("cacheable", True))


class StageRuleTests(unittest.TestCase):
    def test_every_rule_objects_exactly_when_its_cases_say(self):
        for case in CASES:
            with self.subTest(rule=case["rule"], case=case["name"]):
                settings = dict(case.get("call", {}))
                if "channel" in settings:
                    settings["channel"] = CHANNELS[settings["channel"]]
                call = FakeCall(**settings)
                verdict = RULES[case["rule"]](**case.get("rule_args", {})).check(subject(case, call))
                self.assertEqual(verdict is not None, case["objects"])
                if verdict is not None:
                    self.assertEqual(verdict.rule, case["rule"])
                    self.assertEqual(list(verdict.counts), case["counts"])
                    self.assertEqual(verdict.outcome, case.get("outcome"))
                    self.assertEqual(verdict.route, case.get("route"))
                    if "reason" in case:
                        self.assertEqual(verdict.reason, case["reason"])

    def test_every_rule_has_cases_both_ways(self):
        for name in RULES:
            outcomes = {case["objects"] for case in CASES if case["rule"] == name}
            self.assertEqual(outcomes, {True, False}, name)

    def test_the_taint_rule_marks_the_call(self):
        call = FakeCall()
        said = "I am allergic to peanuts"
        question.CallContextTaint().check(VoiceTurn(said, call, WordRuleClassifier().classify(said)))
        self.assertTrue(call.tainted)


if __name__ == "__main__":
    unittest.main()
