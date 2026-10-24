"""The voice adapters never run their blocking calls on asyncio's default thread pool (CI3).

That pool has min(32, CPUs + 4) threads, so on a small machine with many calls and a slow
server the adapters' blocking calls queued behind each other and a call took seconds, not
the latency budget. The SDK's own pools (voice_async) are sized for live calls. Here the
loop's default pool records where each job came from: none may come from the SDK's code.
Pipecat, LiveKit and Bolna run when installed; the custom loops are the controls.
"""
import asyncio
import concurrent.futures
import contextvars
import os
import re
import sys
import unittest

import crowkis

from conformance import ConformanceStore, agent_id
from conformance_drivers import DRIVERS
from crowkis.voice_async import _on_server_pool

TURNS = [
    {"say": "what are your opening hours", "reply": ["We are open nine to five."], "expect": {"llm": True}},
    {"say": "do you deliver on sundays", "reply": ["Yes, every day of the week."], "expect": {"llm": True}},
]


SDK_DIR = os.path.dirname(os.path.abspath(crowkis.__file__))


def _caller_file() -> str:
    """The first file on the stack outside asyncio, the thread pool and this test: the code
    that handed the job to the default pool."""
    frame = sys._getframe(2)
    while frame is not None:
        path = os.path.abspath(frame.f_code.co_filename)
        machinery = any(os.sep + part + os.sep in path for part in ("asyncio", "concurrent"))
        if not machinery and path != os.path.abspath(__file__):
            return path
        frame = frame.f_back
    return ""


class RecordingPool(concurrent.futures.ThreadPoolExecutor):
    """The loop's default pool, noting which file handed it each job."""

    def __init__(self):
        super().__init__(max_workers=4)
        self.callers = []

    def submit(self, fn, *args, **kwargs):
        self.callers.append(_caller_file())
        return super().submit(fn, *args, **kwargs)


class AdapterPoolTests(unittest.TestCase):
    def test_no_adapter_uses_the_default_pool(self):
        ran = 0
        for driver in DRIVERS:
            with self.subTest(adapter=driver.name):
                if not driver.supported:
                    self.skipTest(f"{driver.name}: framework not installed")
                pool = RecordingPool()

                async def run():
                    asyncio.get_running_loop().set_default_executor(pool)
                    return await driver.call(ConformanceStore(), TURNS, agent_id())

                try:
                    with driver.active():
                        heard = asyncio.run(run())
                finally:
                    pool.shutdown(wait=True)
                self.assertEqual([h.heard for h in heard], ["We are open nine to five.", "Yes, every day of the week."])
                ours = [path for path in pool.callers if path.startswith(SDK_DIR + os.sep)]
                self.assertEqual(ours, [], "the SDK handed these jobs to asyncio's default pool")
                ran += 1
        self.assertGreater(ran, 0)


# asyncio.to_thread, or run_in_executor on the default pool (None), anywhere in the SDK.
DEFAULT_POOL_CALL = re.compile(r"asyncio\.to_thread\(|run_in_executor\(\s*None")
TRACE = contextvars.ContextVar("trace", default="none")


class ServerPoolTests(unittest.TestCase):
    def test_no_sdk_code_uses_the_default_pool(self):
        found = []
        for folder, _, files in os.walk(SDK_DIR):
            for name in files:
                if name.endswith(".py"):
                    path = os.path.join(folder, name)
                    with open(path, encoding="utf-8") as source:
                        for number, line in enumerate(source, 1):
                            if DEFAULT_POOL_CALL.search(line):
                                found.append(f"{os.path.relpath(path, SDK_DIR)}:{number}")
        self.assertEqual(found, [])

    def test_a_server_pool_call_sees_the_callers_context(self):
        # asyncio.to_thread passed contextvars (tracing spans, log context) to the thread; so must this.
        async def run():
            TRACE.set("call-42")
            return await _on_server_pool(TRACE.get)

        self.assertEqual(asyncio.run(run()), "call-42")


if __name__ == "__main__":
    unittest.main()
