"""Replays the golden inputs through today's pipelines and records every decision (v4 P0).

Two pipelines, the same calls: ``VoiceReplay`` (VoiceSession: decide, then record the
reply) and ``ChatReplay`` (CallSession: handle, then record_answer, with the stand-in frames
of fixtures/golden/inputs.json). Each suite runs its calls in order on one ``GoldenStore``,
so a later caller can be served what an earlier one saved. node/golden.js is the Node twin
and must write the same files.

Write the files: ``python tests/golden/replay.py`` from python/. test_golden.py checks them.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from crowkis import Agent, CacheHit, VoiceSession
from crowkis.session import CallSession
from crowkis.turn import TurnFrame

ROOT = Path(__file__).resolve().parents[3]
GOLDEN = ROOT / "fixtures" / "golden"
INPUTS = json.loads((GOLDEN / "inputs.json").read_text("utf-8"))
PHRASES = json.loads((ROOT / "fixtures" / "voice-rule-phrases.json").read_text("utf-8"))["phrases"]
PHRASE_REPLY = "Here is the answer."
AGENT_ID = "golden"
HIT_CONFIDENCE = 0.99


class GoldenStore:
    """The server: answers matched on the exact question within one segment, shared answers
    and answer shapes apart. ``down``: every lookup and write fails, as an unreachable server."""

    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.answers: Dict[Tuple[str, str, bool], str] = {}
        self.writes: List[list] = []

    def cget_hit(self, query: str, **kwargs: Any) -> Optional[CacheHit]:
        self._fail_if_down()
        found = self.answers.get((kwargs.get("segment") or "", query, bool(kwargs.get("template"))))
        if found is None:
            return None
        return CacheHit(response=found.encode(), similarity=HIT_CONFIDENCE, ttl_remaining=600,
                        matched_key=b"k", confidence=HIT_CONFIDENCE, hit_type="semantic")

    def cset(self, query: str, response: str, **kwargs: Any) -> None:
        self._fail_if_down()
        segment, template = kwargs.get("segment") or "", bool(kwargs.get("template"))
        self.writes.append([segment, query, response, template])
        self.answers[(segment, query, template)] = response

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
    """One call through VoiceSession: decide each turn, record the reply when the model is asked."""

    pipeline = "voice"

    def call(self, store: GoldenStore, turns: List[Dict[str, str]]) -> List[Dict]:
        session = VoiceSession(Agent(AGENT_ID, client=store), voice="v")
        return [self._turn(session, turn) for turn in turns]

    @staticmethod
    def _turn(session: VoiceSession, turn: Dict[str, str]) -> Dict:
        decision = session.decide(turn["say"])
        record = {"say": turn["say"], "action": decision.action, "rule": decision.rule,
                  "reason": decision.reason, "cacheable": decision.cacheable, "sees": _sees(decision.messages)}
        if decision.needs_model:
            decision = session.record(decision, turn["reply"])
            record.update(stored=decision.stored, save_rule=decision.save_rule, not_stored=decision.not_stored)
        else:
            record["text"] = decision.text
        return record


class ChatReplay:
    """One call through CallSession: handle each turn, record the reply when the model is asked."""

    pipeline = "chat"

    def call(self, store: GoldenStore, turns: List[Dict[str, str]]) -> List[Dict]:
        session = CallSession(Agent(AGENT_ID, client=store), ScriptedUnderstander(INPUTS["frames"]),
                              latency_budget_ms=None, understand_budget_ms=None)
        return [self._turn(session, turn) for turn in turns]

    @staticmethod
    def _turn(session: CallSession, turn: Dict[str, str]) -> Dict:
        result = session.handle(turn["say"])
        verdict = result.verdict
        record = {"say": turn["say"], "route": result.route, "reason": result.reason,
                  "needs_model": result.needs_model, "sees": _sees(result.messages),
                  "key": verdict.key if verdict else None, "segment": verdict.segment if verdict else None}
        if result.needs_model:
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
    """Every call of a suite in order on one store; what each turn decided, and every write."""
    store = GoldenStore()
    decisions = {}
    for call in calls:
        store.down = bool(call.get("down"))
        decisions[call["id"]] = pipeline.call(store, call["turns"])
    return {"calls": decisions, "writes": store.writes}


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
