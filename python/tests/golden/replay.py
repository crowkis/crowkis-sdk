"""Replays the golden inputs through today's pipelines and records every decision (v4 P0).

Two pipelines, the same calls: ``VoiceReplay`` (VoiceSession: decide, then record the
reply) and ``ChatReplay`` (CallSession: handle, then record_answer, with the stand-in frames
of fixtures/golden/inputs.json). Calls run in order; calls of one ``store`` group share one
``GoldenStore`` (a whole stress suite shares one, so a later caller can be served what an
earlier one saved; each conformance scenario and hit-guard call has its own). Each call
records every turn's decision and the session's counters. node/golden.js is the Node twin
and must reproduce the same files.

Write the files: ``python tests/golden/replay.py`` from python/. test_golden.py checks them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from crowkis import Agent, CacheHit, VoiceSession
from crowkis.channels.call_session import CallSession
from crowkis.understanding.model.frame import TurnFrame

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "fixtures" / "golden"
INPUTS = json.loads((GOLDEN / "inputs.json").read_text("utf-8"))
PHRASES = json.loads((ROOT / "fixtures" / "voice-rule-phrases.json").read_text("utf-8"))["phrases"]
PHRASE_REPLY = "Here is the answer."
AGENT_ID = "golden"
HIT_CONFIDENCE = 0.99
SUITE_STORE = "suite"
# stats() keys derived from the counts: left out, so they are compared as counts only.
DERIVED_STATS = ("cache_hit_pct", "filler_hit_pct", "model_calls_avoided_pct")


class GoldenStore:
    """The server: an answer is found by its question (an ``exact`` hit) or by a reworded
    question in ``aliases`` (a ``semantic`` one), within one segment, shared answers and answer
    shapes apart, with the flags the server's decision engine sets. ``engine``: whether that
    engine is on. ``down``: every lookup and write fails, as an unreachable server."""

    def __init__(self, seed: List[Dict], aliases: Dict[str, str], engine: bool = False, pool: str = "") -> None:
        self.down = False
        self.engine = engine
        self.aliases = dict(aliases)
        self.answers: Dict[Tuple[str, str, bool], Dict] = {}
        self.writes: List[list] = []
        for entry in seed:
            self.answers[(pool, entry["question"], bool(entry.get("template")))] = entry

    def cget_hit(self, query: str, **kwargs: Any) -> Optional[CacheHit]:
        self._fail_if_down()
        asked = self.aliases.get(query, query)
        found = self.answers.get((kwargs.get("segment") or "", asked, bool(kwargs.get("template"))))
        if found is None:
            return None
        return CacheHit(response=found["answer"].encode(), similarity=HIT_CONFIDENCE, ttl_remaining=600,
                        matched_key=b"k", confidence=HIT_CONFIDENCE,
                        hit_type="exact" if asked == query else "semantic",
                        vouched=bool(found.get("vouched")), commitment=bool(found.get("commitment")))

    def cset(self, query: str, response: str, **kwargs: Any) -> None:
        self._fail_if_down()
        segment, template = kwargs.get("segment") or "", bool(kwargs.get("template"))
        self.writes.append([segment, query, response, template])
        self.answers[(segment, query, template)] = {"question": query, "answer": response}

    def cdecision(self, query: str, **kwargs: Any) -> Dict[str, bool]:
        return {"engine": self.engine}

    def ctoolget(self, *args: Any, **kwargs: Any) -> None:
        return None

    def ctoolset(self, *args: Any, **kwargs: Any) -> None:
        return None

    def close(self) -> None:
        pass

    def _fail_if_down(self) -> None:
        if self.down:
            raise ConnectionRefusedError("crowkis server down")


class ScriptedUnderstander:
    """Chat's understanding step, answered from the frozen stand-in frames."""

    def __init__(self, frames: Dict[str, Dict]) -> None:
        self.frames = frames

    def understand(self, turn: str, state: Any) -> TurnFrame:
        return TurnFrame.from_dict(self.frames.get(turn))


def _sees(messages: Optional[List[Dict[str, str]]]) -> Optional[List[str]]:
    return None if messages is None else [f"{m['role']}: {m['content']}" for m in messages]


class VoiceReplay:
    """One call through VoiceSession: decide each turn, record the reply when the model is asked
    (as a tool's result, or after the caller talked over it, when the turn says so)."""

    pipeline = "voice"
    pool = "kb=1"  # where the seeded answers live: the one pool per tenant

    def call(self, store: GoldenStore, call: Dict) -> Dict:
        session = VoiceSession(Agent(AGENT_ID, client=store), voice="v", **call.get("options", {}))
        turns = [self._turn(session, turn) for turn in call["turns"]]
        stats = {k: v for k, v in session.stats().items() if k not in DERIVED_STATS}
        return {"turns": turns, "stats": stats}

    @staticmethod
    def _turn(session: VoiceSession, turn: Dict) -> Dict:
        decision = session.decide(turn["say"])
        record = {"say": turn["say"], "action": decision.action, "rule": decision.rule,
                  "reason": decision.reason, "cacheable": decision.cacheable, "sees": _sees(decision.messages)}
        if decision.needs_model:
            if turn.get("barge_in"):
                session.cancel()
            decision = session.record(decision, turn["reply"], private=bool(turn.get("tool")))
            record.update(stored=decision.stored, save_rule=decision.save_rule, not_stored=decision.not_stored)
        else:
            record["text"] = decision.text
        return record


class ChatReplay:
    """One call through CallSession: handle each turn, record the reply when the model is asked
    (after the caller talked over it, when the turn says so)."""

    pipeline = "chat"
    pool = ""

    def call(self, store: GoldenStore, call: Dict) -> Dict:
        session = CallSession(Agent(AGENT_ID, client=store), ScriptedUnderstander(INPUTS["frames"]),
                              latency_budget_ms=None, understand_budget_ms=None)
        turns = [self._turn(session, turn) for turn in call["turns"]]
        return {"turns": turns, "stats": dict(session.counts)}

    @staticmethod
    def _turn(session: CallSession, turn: Dict) -> Dict:
        result = session.handle(turn["say"])
        verdict = result.verdict
        record = {"say": turn["say"], "route": result.route, "reason": result.reason,
                  "needs_model": result.needs_model, "sees": _sees(result.messages),
                  "key": verdict.key if verdict else None, "segment": verdict.segment if verdict else None}
        if result.needs_model:
            if turn.get("barge_in"):
                session.cancel()
            record["outcome"] = session.record_answer(result, turn["reply"])
        else:
            record["text"] = result.text
        return record


def phrase_calls() -> List[Dict]:
    """The 277 rule phrases, each said on its own by a new caller."""
    return [{"id": case["phrase"], "turns": [{"say": case["phrase"], "reply": PHRASE_REPLY}]} for case in PHRASES]


def suites() -> Dict[str, List[Dict]]:
    return {"phrases": phrase_calls(), **INPUTS["suites"]}


def replay(pipeline: Any, calls: List[Dict]) -> Dict:
    """Every call of a suite in order, a store per store group; what each call decided, and
    every write each store took."""
    stores: Dict[str, GoldenStore] = {}
    decisions = {}
    for call in calls:
        group = call.get("store", SUITE_STORE)
        if group not in stores:
            stores[group] = GoldenStore(call.get("seed", []), call.get("aliases", {}), bool(call.get("engine")), pipeline.pool)
        store = stores[group]
        store.down = bool(call.get("down"))
        decisions[call["id"]] = pipeline.call(store, call)
    return {"calls": decisions, "writes": {group: store.writes for group, store in stores.items()}}


def golden_path(pipeline: str, suite: str) -> Path:
    return GOLDEN / pipeline / f"{suite}.json"


def as_text(recorded: Dict) -> str:
    return json.dumps(recorded, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def write_all() -> None:
    for pipeline in (VoiceReplay(), ChatReplay()):
        for suite, calls in suites().items():
            path = golden_path(pipeline.pipeline, suite)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(as_text(replay(pipeline, calls)), "utf-8", newline="\n")
            print(path)


if __name__ == "__main__":
    write_all()
