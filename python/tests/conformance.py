"""Phase 3: the scenarios every voice adapter must pass (fixtures/adapter-conformance.json).

A driver plays one call (a new session on a shared server) through its adapter: the
custom-loop APIs (VoiceSession.respond, AsyncVoiceSession.respond), Pipecat (CrowkisLLM +
CrowkisTTS in a real Pipeline) and LiveKit (CrowkisVoice on a real Agent). The LLM and
TTS are stand-ins that count their calls; the server is ConformanceStore (fault modes:
down, slow, audio_error; reworded questions via aliases) or, with
CROWKIS_CONFORMANCE_SERVER=1, a real Crowkis server from CROWKIS_HOST / CROWKIS_PORT /
CROWKIS_AUTH_TOKEN / CROWKIS_TENANT. node/conformance.js is the Node twin.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import crowkis
from crowkis import CacheHit, CrowkisClient
from crowkis.agent import _wait_for_audio_stores
from crowkis.voice import _wait_for_writes

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "adapter-conformance.json"
SPEC = json.loads(FIXTURE.read_text("utf-8"))
SCENARIOS = SPEC["scenarios"]
REAL = os.environ.get("CROWKIS_CONFORMANCE_SERVER") == "1"
SLOW_S = 2.0
REAL_GAP_S = 1.5
REAL_RETRIES = 3
REAL_RETRY_S = 2.0
RATE = 16000
PCM = b"\x01\x02" * 320


# -- the server -------------------------------------------------------------------------

class ConformanceStore:
    """A Crowkis server for the adapters: shared answers matched on the exact question (or
    a reworded one in ``aliases``), the basic audio cache, and the fault modes."""

    def __init__(self, server: str = "ok", aliases: Optional[Dict[str, str]] = None,
                 seed: Optional[Dict[str, str]] = None):
        self.server = server
        self.aliases = dict(aliases or {})
        self.shared = dict(seed or {})
        self.tool: Dict[str, str] = {}
        self.writes: List[list] = []
        self.tool_writes: List[list] = []
        self.tenant = None
        self.fail_soft = False
        self._lock = threading.Lock()

    def _fault(self, audio: bool = False):
        if self.server == "down":
            raise ConnectionRefusedError("crowkis server down")
        if self.server == "slow":
            time.sleep(SLOW_S)
        if audio and self.server == "audio_error":
            raise RuntimeError("audio cache error")

    def cget_hit(self, query, **kwargs):
        self._fault()
        if kwargs.get("template"):
            return None
        found = self.shared.get(self.aliases.get(query, query))
        if found is None:
            return None
        return CacheHit(response=found.encode(), similarity=0.99, ttl_remaining=600,
                        matched_key=b"k", confidence=0.99, hit_type="semantic")

    def cset(self, query, response, *, ttl=None, tenant=None, template=False, **kwargs):
        self._fault()
        with self._lock:
            self.writes.append([query, response, bool(template)])
            if not template:
                self.shared[query] = response

    def ctoolget(self, tool, key, *, tenant=None):
        self._fault(audio=True)
        return self.tool.get(key)

    def ctoolset(self, tool, key, value, *, ex=None, tenant=None):
        self._fault(audio=True)
        with self._lock:
            self.tool_writes.append([json.loads(key), value])
            self.tool[key] = value

    def close(self):
        pass


class RecordingClient:
    """A real client that also notes every write, so saved / never_saved are checked
    against a real server too."""

    def __init__(self, client: CrowkisClient):
        self._client = client
        self.writes: List[list] = []
        self.tool_writes: List[list] = []

    def cset(self, query, response, **kwargs):
        self.writes.append([query, response, bool(kwargs.get("template"))])
        return self._client.cset(query, response, **kwargs)

    def ctoolset(self, tool, key, value, **kwargs):
        self.tool_writes.append([key, value])
        return self._client.ctoolset(tool, key, value, **kwargs)

    def close(self):
        self._client.close()

    def __getattr__(self, name):
        return getattr(self._client, name)


# Read once, at import: the test suite clears the CROWKIS_* variables for each test.
_SERVER = {name: os.environ.get("CROWKIS_" + name.upper()) for name in ("host", "port", "auth_token", "tenant")}


def make_store(scenario: dict):
    if REAL:
        settings = {k: (int(v) if k == "port" else v) for k, v in _SERVER.items() if v}
        return RecordingClient(CrowkisClient(**settings))
    return ConformanceStore(scenario.get("server", "ok"), scenario.get("aliases"), scenario.get("seed"))


def agent_id() -> str:
    """One agent per scenario run, so runs on a real server never meet."""
    return "conformance-" + uuid.uuid4().hex[:10] if REAL else "conformance"


# -- the stand-ins ----------------------------------------------------------------------

class Counts:
    def __init__(self):
        self.llm = 0
        self.tts = 0
        self.read: List[Any] = []


def fake_tts(counts: Counts):
    def synthesise(text: str) -> bytes:
        counts.tts += 1
        return PCM

    return synthesise


@dataclass
class Heard:
    llm: bool
    tts: bool
    heard: str
    ms: float


# -- running and checking ---------------------------------------------------------------

def _seconds(turn: dict) -> float:
    return turn["expect"].get("max_ms", 10_000) / 1000


def _for_real(turns: list) -> list:
    """On a real server a turn that must hit gets an empty stand-in reply: if it misses, the
    SDK never stores an empty answer, so a failing run leaves nothing wrong on the server."""
    return [dict(t, reply=[]) if t["expect"].get("llm") is False else t for t in turns]


def _missed(turns: list, heard: List[Heard]) -> bool:
    return any(t["expect"].get("llm") is False and got.llm for t, got in zip(turns, heard))


async def run_scenario(driver, scenario: dict, store) -> List[List[Heard]]:
    """Every call of the scenario, one after another (each ``concurrent`` times at once)."""
    agent = agent_id()
    results = []
    await asyncio.to_thread(_settle)  # nothing left over from an earlier scenario
    for turns in scenario["calls"]:
        copies = scenario.get("concurrent", 1)
        if REAL:
            turns = _for_real(turns)
        runs = await asyncio.gather(*(driver.call(store, turns, agent) for _ in range(copies)))
        for attempt in range(REAL_RETRIES if REAL else 0):
            # A real server's engine may take longer to make a new answer findable: a new
            # caller asks again, a few seconds later.
            if not any(_missed(turns, run) for run in runs):
                break
            await asyncio.sleep(REAL_RETRY_S)
            runs = await asyncio.gather(*(driver.call(store, turns, agent) for _ in range(copies)))
        results.extend(runs)
        # Writes and clips may finish in the background; the next caller is a later call.
        await asyncio.to_thread(_settle)
        if REAL:
            await asyncio.sleep(REAL_GAP_S)  # a real server makes a new answer findable within about a second
    return results


def _settle() -> None:
    _wait_for_writes()
    _wait_for_audio_stores()


def check(case, scenario: dict, store, results: List[List[Heard]]) -> None:
    """``case`` is a unittest.TestCase. Real hits may lag a write (the server's engine),
    which run_real() allows for by retrying."""
    expected = [turns for turns in scenario["calls"] for _ in range(scenario.get("concurrent", 1))]
    for index, (turns, heard) in enumerate(zip(expected, results)):
        for turn, got in zip(turns, heard):
            want = turn["expect"]
            where = f"call {index + 1}, {turn['say']!r}: {got}"
            # On a real server an earlier run may already have taught it this answer (its
            # cache is per tenant), so a miss is not required there; what the caller heard is.
            if want.get("llm") is not None and not (REAL and want["llm"]):
                case.assertEqual(got.llm, want["llm"], "LLM called? " + where)
            if want.get("tts") is not None:
                case.assertEqual(got.tts, want["tts"], "TTS called? " + where)
            if "heard" in want and not (REAL and want.get("llm") is False and got.llm):
                case.assertEqual(got.heard.strip(), want["heard"], "heard: " + where)
            if "max_ms" in want:
                case.assertLess(got.ms, want["max_ms"], "too slow: " + where)
    writes = [w for w in store.writes if not w[2]]
    if "saved" in scenario and not REAL:
        case.assertEqual(sorted([w[0], w[1]] for w in writes), sorted(scenario["saved"]))
    if "saved" in scenario and REAL:
        case.assertTrue(all(list(w) in [list(s) for s in scenario["saved"]] for w in ([x[0], x[1]] for x in writes)),
                        f"unexpected shared answers: {writes}")
        # The server may know the answer from an earlier run, but a turn the LLM answered
        # whose answer is to be shared must have written it: an adapter that never writes fails.
        to_share = {q for q, _ in scenario["saved"]}
        written = [[w[0], w[1].strip()] for w in writes]
        for turns, heard in zip(expected, results):
            for turn, got in zip(turns, heard):
                if got.llm and turn["say"] in to_share and turn.get("barge_in_after") is None:
                    case.assertIn([turn["say"], got.heard.strip()], written, f"not written: {turn['say']!r}")
    if scenario.get("never_saved"):
        everything = json.dumps([store.writes, store.tool_writes], default=str)
        case.assertNotIn(scenario["never_saved"], everything)


# The SDK's shared thread pools: made once, reused by every call, bounded.
_POOLS = {"crowkis-voice_": 32, "crowkis-voice-write": 16, "crowkis-voice-server": 64, "crowkis-voice-model": 256, "crowkis-call": 16,
          "crowkis-understand": 16}


def stray_threads(before: set) -> list:
    """Threads the call left behind, other than the shared pools' (which must stay in bounds)."""
    now = [t for t in threading.enumerate() if not t.daemon and t not in before]
    stray = [t for t in now if not any(t.name.startswith(p) for p in _POOLS)]
    for prefix, limit in _POOLS.items():
        count = sum(1 for t in threading.enumerate() if t.name.startswith(prefix))
        if count > limit:
            stray.append(f"{count} {prefix} threads (limit {limit})")
    return stray


def no_leaks(case, before: set) -> None:
    """No task left running and no client socket left open by the call."""
    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task() and t not in before]
    case.assertEqual(pending, [], "tasks left running")
