"""Phase 3: every voice adapter passes the same scenarios (fixtures/adapter-conformance.json).

    python -m pytest tests/test_conformance.py                  # stand-in server
    CROWKIS_CONFORMANCE_SERVER=1 python -m pytest tests/test_conformance.py   # a real server

Pipecat and LiveKit run when installed (pinned in CI: pipecat-ai 1.13.0, livekit-agents
1.8.8); without them their cases are skipped. node/test-conformance.js runs the same file.
"""

import asyncio
import threading
import unittest

from conformance import REAL, SCENARIOS, check, make_store, no_leaks, run_scenario, stray_threads
from conformance_drivers import DRIVERS


class ConformanceTests(unittest.TestCase):
    def test_every_adapter_passes_every_scenario(self):
        ran = 0
        for driver in DRIVERS:
            for scenario in SCENARIOS:
                if REAL and not scenario.get("real"):
                    continue
                with self.subTest(adapter=driver.name, scenario=scenario["name"]):
                    if not driver.supported:
                        self.skipTest(f"{driver.name}: framework not installed")
                    self._run(driver, scenario)
                    ran += 1
        self.assertGreater(ran, 0)

    def _run(self, driver, scenario):
        store = make_store(scenario)
        threads = set(threading.enumerate())

        async def run():
            before = set(asyncio.all_tasks())
            results = await run_scenario(driver, scenario, store)
            await asyncio.sleep(0)
            no_leaks(self, before)
            return results

        with driver.active():
            results = asyncio.run(run())
        check(self, scenario, store, results)
        self.assertEqual(stray_threads(threads), [], "threads left running")


if __name__ == "__main__":
    unittest.main()
