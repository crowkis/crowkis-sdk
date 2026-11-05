"""v4 P0: today's decisions, pinned (fixtures/golden/<pipeline>/<suite>.json).

Every v4 refactor phase must reproduce these files exactly. A difference is a behaviour
change: it needs the owner's OK, then the files are rewritten with
``python tests/golden/replay.py`` (from python/) and the change is named in the commit.
node/test-golden.js checks the same files, so the two languages decide the same."""
import unittest

from golden.replay import VoiceReplay, as_text, golden_path, replay, suites


class GoldenDecisionTests(unittest.TestCase):
    def test_every_pipeline_reproduces_its_golden_decisions(self):
        for pipeline in (VoiceReplay(),):
            for suite, calls in suites().items():
                with self.subTest(pipeline=pipeline.pipeline, suite=suite):
                    expected = golden_path(pipeline.pipeline, suite).read_text("utf-8")
                    self.assertEqual(as_text(replay(pipeline, calls)), expected)


if __name__ == "__main__":
    unittest.main()
