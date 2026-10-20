"""The shared voice adapter layer (crowkis.voice_turns) does what the Pipecat processors
do, event for event, and the scenario file the Node port checks against says the same.

The Pipecat processors are now thin wrappers over this layer; every existing Pipecat test
passes unchanged. Here each scenario in voice_turns_scenarios.py is played twice, through
the layer's plain events and through the Pipecat processors as frames, and both must end
the same (store writes, clips kept, answer reports, transcript, served turns)."""

import asyncio
import json
import os
import unittest

from test_voice_stress_bugs import _pipecat
from voice_turns_scenarios import FIXTURE, SCENARIOS, run_events, run_pipecat


def _expected():
    return [{"name": s["name"], **{k: s[k] for k in ("seed", "options", "addon", "holds", "no_queue") if k in s},
             "events": s["events"], "expected": asyncio.run(run_events(s))} for s in SCENARIOS]


class SharedLayerTests(unittest.TestCase):
    def test_every_scenario_ends_the_same_through_pipecat_frames(self):
        pc, F, LLMContext = _pipecat()
        for scenario in SCENARIOS:
            if scenario.get("framework_free"):
                continue  # expect() / a gate with no queue: no Pipecat frame maps to them
            with self.subTest(scenario=scenario["name"]):
                self.assertEqual(asyncio.run(run_events(scenario)), asyncio.run(run_pipecat(scenario, pc, F, LLMContext)))

    def test_the_scenarios_cover_every_outcome(self):
        outcomes = [asyncio.run(run_events(s)) for s in SCENARIOS]
        saved = {r["saved"] for o in outcomes for r in o["reports"]}
        self.assertTrue({"saved", "kept", "private", "not_saved", "non_answer"} <= saved, saved)
        self.assertTrue(any(o["clips"] for o in outcomes))          # a clip kept
        self.assertTrue(any(t[2] for o in outcomes for t in o["turns"]))  # a clip replayed
        self.assertTrue(any(o["audio_clips"] for o in outcomes))     # a clip in the Voice add-on

    def test_the_node_fixture_is_current(self):
        expected = _expected()
        if os.environ.get("CROWKIS_UPDATE_FIXTURES"):
            FIXTURE.parent.mkdir(parents=True, exist_ok=True)
            FIXTURE.write_text(json.dumps(expected, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertTrue(FIXTURE.exists(), f"run with CROWKIS_UPDATE_FIXTURES=1 to write {FIXTURE}")
        self.assertEqual(json.loads(FIXTURE.read_text(encoding="utf-8")), json.loads(json.dumps(expected)))


if __name__ == "__main__":
    unittest.main()
