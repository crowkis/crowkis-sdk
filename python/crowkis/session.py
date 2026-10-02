"""CallSession: one call or chat thread on turn understanding v2.2 (part 4).

Ties the pieces together for each caller turn:

    understand (model slot) -> rule checker -> route -> [lookup] -> answer -> save check
                                                                         -> call state update

Routes
  urgent    the app's ``on_urgent`` hook runs first; the agent answers; never cached
  task      a step of a booking/order the agent is running; the agent answers; never cached
  shared    looked up; a hit is spoken; on a miss the model reads ONLY the shared question,
            and its answer is saved after the save check, with the question type's expiry
  personal  the agent answers with its tools; a verified single-field value may be phrased
            by a registered response shape (``phrase``), never fetched or decided by the cache
  tools     live data or an action: the agent answers with its tools; never cached
  agent     everything else (dialogue, chit-chat, unclear): the agent answers; never cached

Sits next to VoiceSession; existing users are unaffected.
"""

from __future__ import annotations

import concurrent.futures
import copy
import itertools
import re
import string
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .callstate import IDENTITIES, CallState
from .rules import is_non_answer
from .turn import TurnFrame
from .understand import ReplayUnderstander, Understander
from .verify import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT, RuleChecker, Verdict

FILLER = "filler"
MODES = ("full", "replay_only", "off")
Message = Dict[str, str]
_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-call")
_UNDERSTAND = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-understand")
_TRIM = string.punctuation + string.whitespace
_EMAIL = re.compile(r"\S+@\S+")
_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){5,}")
# A first-person claim that something was done. A cached answer must never claim an action.
_ACTION_CLAIM = re.compile(
    r"\b(i\s*(have|'ve)|i\s+just|we\s*(have|'ve))\s+(cancel+ed|booked|refunded|processed|changed|updated|"
    r"reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\b"
    r"|\b(has|have)\s+been\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted)\b", re.I)


@dataclass
class TurnResult:
    turn_id: int
    route: str
    text: Optional[str] = None             # what to say now (cache hit or filler), else None
    needs_model: bool = True
    messages: Optional[List[Message]] = None  # what the model reads; None = the whole call
    frame: Optional[TurnFrame] = None
    verdict: Optional[Verdict] = None
    reason: str = ""

    @property
    def served_from_cache(self) -> bool:
        return self.route == SHARED and self.text is not None


@dataclass
class _Shape:
    template: str
    requires: str


class CallSession:
    """One call. Not thread-safe: one turn at a time (barge-in via ``cancel``).

    ``agent``         a crowkis Agent (lookup and save go through ``ask`` / ``learn``)
    ``understander``  anything with ``understand(turn, state) -> TurnFrame``
    ``on_urgent``     called with (turn, frame) before anything else on an urgent turn
    ``understand_budget_ms``  hard limit on the understanding step; past it (or on any error)
                      the safe fallback (``replay``, exact repeats only) decides, or the agent
                      answers. A late frame is never used.
    ``latency_budget_ms``     hard limit on the cache lookup; past it the model answers.
    ``mode``          "full" (default), "replay_only" (no model: exact repeats of verified
                      questions only) or "off" (share nothing). Switchable at runtime with
                      ``set_mode``: the kill switch for production.
    ``on_event``      monitoring hook, called with a dict after each turn ("turn") and each
                      recorded answer ("answer"). Carries routes, reasons and de-identified keys,
                      never the caller's raw words. Errors in the hook are ignored.
    """

    def __init__(
        self,
        agent: Any,
        understander: Understander,
        *,
        checker: Optional[RuleChecker] = None,
        on_urgent: Optional[Callable[[str, TurnFrame], None]] = None,
        replay: Optional[ReplayUnderstander] = None,
        serve_above: float = 0.92,
        latency_budget_ms: Optional[float] = 300.0,
        understand_budget_ms: Optional[float] = 250.0,
        fillers: Optional[Dict[str, str]] = None,
        mode: str = "full",
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> None:
        for name, value in (("latency_budget_ms", latency_budget_ms), ("understand_budget_ms", understand_budget_ms)):
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive or None, got {value}")
        self.agent = agent
        self.understander = understander
        self.checker = checker or RuleChecker()
        self.on_urgent = on_urgent
        self.replay = replay
        self.serve_above = serve_above
        self.latency_budget_ms = latency_budget_ms
        self.understand_budget_ms = understand_budget_ms
        self.on_event = on_event
        self.mode = "full"
        self.set_mode(mode)
        self.state = CallState()
        self._fillers = {self._norm(k): v for k, v in (fillers or {}).items()}
        self._shapes: Dict[str, _Shape] = {}
        self._ids = itertools.count(1)
        self._open: Optional[TurnResult] = None
        self._cancelled: set = set()
        self.counts: Dict[str, int] = {k: 0 for k in (
            URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved", "save_refused",
            "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
            "cancelled", "sharing_off")}

    def set_mode(self, mode: str) -> None:
        """Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self.mode = mode

    # --- one caller turn --------------------------------------------------------------

    def handle(self, turn: str) -> TurnResult:
        tid = next(self._ids)
        text = " ".join((turn or "").split())
        if not text:
            return self._open_turn(TurnResult(tid, AGENT, reason="empty"))
        filler = self._fillers.get(self._norm(text))
        if filler is not None:
            self.counts[FILLER] += 1
            self.state.note_agent_reply(filler)
            return TurnResult(tid, FILLER, text=filler, needs_model=False, reason="registered filler")

        if self.mode == "off":
            self.counts["sharing_off"] += 1
            result = self._open_turn(TurnResult(tid, AGENT, reason="sharing off"))
            self._emit({"type": "turn", "turn_id": tid, "route": AGENT, "reasons": ["mode_off"], "shared": False})
            return result
        frame = self._understand(text)
        verdict = self.checker.check(frame, text, self.state)
        self.state.apply(frame, shared=verdict.shared)
        self.counts[verdict.route] += 1

        if verdict.route == URGENT and self.on_urgent is not None:
            try:
                self.on_urgent(text, frame)
            except Exception:  # noqa: BLE001 - the hook must not take the call down
                pass
        event = {"type": "turn", "turn_id": tid, "route": verdict.route, "reasons": list(verdict.reasons),
                 "shared": verdict.shared, "urgent": frame.urgent, "kind": frame.kind,
                 "confidence": frame.confidence, "question": verdict.question, "key": verdict.key,
                 "question_type": frame.question_type if verdict.shared else None}
        if verdict.route != SHARED:
            self._emit(dict(event, hit=False))
            return self._open_turn(TurnResult(tid, verdict.route, frame=frame, verdict=verdict,
                                              reason=";".join(verdict.reasons)))

        if self.replay is not None:
            self.replay.remember(text, verdict.question, frame.question_type)
        hit = self._lookup(verdict.key)
        if hit is not None:
            self.counts["hits"] += 1
            result = TurnResult(tid, SHARED, text=hit, needs_model=False, frame=frame, verdict=verdict,
                                reason="cache hit")
            self.state.note_agent_reply(hit)
            self._emit(dict(event, hit=True))
            return self._open_turn(result)
        self._emit(dict(event, hit=False))
        messages = [{"role": "user", "content": verdict.question}]
        if verdict.attributes:
            facts = "; ".join(f"{k}: {v}" for k, v in sorted(verdict.attributes.items()))
            messages.insert(0, {"role": "system", "content": f"Answer for: {facts}."})
        return self._open_turn(TurnResult(tid, SHARED, frame=frame, verdict=verdict, messages=messages,
                                          reason="cache miss"))

    def record_answer(self, result: TurnResult, answer: str, *, mentions: tuple = (),
                      task: Optional[str] = None) -> str:
        outcome = self._record(result, answer, mentions, task)
        self._emit({"type": "answer", "turn_id": result.turn_id, "route": result.route, "outcome": outcome,
                    "key": result.verdict.key if result.verdict else None})
        return outcome

    def _record(self, result: TurnResult, answer: str, mentions: tuple, task: Optional[str]) -> str:
        """The agent answered ``result``. Saves it when allowed and updates the call state.

        ``mentions`` are the places/products/options the agent named; ``task`` is set when
        the agent starts collecting details for a booking, order or account change.
        Returns what happened: saved | not_shared | refused:<why> | cancelled | stale.
        """
        if result.turn_id in self._cancelled:
            self.counts["cancelled"] += 1
            return "cancelled"
        if self._open is None or self._open.turn_id != result.turn_id:
            return "stale"  # an older turn finishing after a newer one started: never saved
        self._open = None
        self.state.note_agent_reply(answer, mentions, task)
        if result.route != SHARED or result.text is not None or result.verdict is None:
            return "not_shared"
        why = self.save_check(answer, result.verdict, result.frame)
        if why:
            self.counts["save_refused"] += 1
            return "refused:" + why
        try:
            self.agent.learn(result.verdict.key, answer, ttl=result.verdict.ttl)
        except Exception:  # noqa: BLE001 - a refused write must not end a call
            self.counts["save_refused"] += 1
            return "refused:write_failed"
        self.counts["saved"] += 1
        return "saved"

    def cancel(self) -> bool:
        """Barge-in: the open turn is abandoned and its answer will never be saved."""
        if self._open is None:
            return False
        self._cancelled.add(self._open.turn_id)
        self._open = None
        return True

    # --- personal answers: phrasing a verified value, never fetching or deciding it -----

    def register_shape(self, field_name: str, template: str, *, requires: str = "identified") -> None:
        """A response shape for one field returned by the agent's own tools,
        e.g. ``register_shape("eta", "Your order arrives on {eta}.", requires="identified")``."""
        if requires not in IDENTITIES:
            raise ValueError(f"requires must be one of {IDENTITIES}")
        if "{" + field_name + "}" not in template:
            raise ValueError("the template must contain the field's own slot")
        self._shapes[field_name] = _Shape(template, requires)

    def phrase(self, field_name: str, value: Any, *, subject: str = "self") -> Optional[str]:
        """Phrase a value the agent's tool returned for this caller. None when there is no
        shape, the caller is not verified enough, or the value is about someone else."""
        shape = self._shapes.get(field_name)
        if shape is None or subject != "self" or value in (None, ""):
            return None
        if IDENTITIES.index(self.state.identity) < IDENTITIES.index(shape.requires):
            return None
        return shape.template.replace("{" + field_name + "}", str(value))

    # --- the save check -----------------------------------------------------------------

    def save_check(self, answer: str, verdict: Verdict, frame: Optional[TurnFrame] = None) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        text = " ".join((answer or "").split())
        if not text:
            return "empty"
        if is_non_answer(text):
            return "non_answer"
        if _EMAIL.search(text) or _LONG_DIGITS.search(text):
            return "identifying"
        if frame is not None and any(t.lower() in text.lower() for t in frame.identifying_texts):
            return "identifying"
        if _ACTION_CLAIM.search(text):
            return "action_claim"
        for name, attr in self.state.attributes.items():
            if name not in verdict.attributes and attr.value and re.search(
                    r"\b" + re.escape(attr.value) + r"\b", text, re.I):
                return "attribute_not_in_key"
        return None

    # --- internals ----------------------------------------------------------------------

    def _emit(self, event: Dict[str, Any]) -> None:
        if self.on_event is None:
            return
        try:
            self.on_event(event)
        except Exception:  # noqa: BLE001 - monitoring must never affect the call
            pass

    def _open_turn(self, result: TurnResult) -> TurnResult:
        self._open = result
        return result

    def _understand(self, text: str) -> TurnFrame:
        """The model's frame within the budget; otherwise the safe fallback's, or an uncertain one."""
        if self.mode == "replay_only":
            if self.replay is None:
                return TurnFrame.from_dict(None)
            self.counts["fallback_used"] += 1
            return self.replay.understand(text, self.state)
        try:
            if self.understand_budget_ms is None:
                return self.understander.understand(text, self.state)
            # The worker gets its own copy of the state: a late model must never see (or race
            # with) the state of a later turn. Its late answer is simply discarded.
            state = copy.deepcopy(self.state)
            return _UNDERSTAND.submit(self.understander.understand, text, state).result(
                timeout=self.understand_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.counts["understand_timeouts"] += 1
        except Exception:  # noqa: BLE001 - understanding failing must never end a call
            self.counts["understand_errors"] += 1
        if self.replay is not None and self.replay is not self.understander:
            self.counts["fallback_used"] += 1
            try:
                return self.replay.understand(text, self.state)
            except Exception:  # noqa: BLE001
                pass
        return TurnFrame.from_dict(None)

    def _lookup(self, key: str) -> Optional[str]:
        call = lambda: self.agent.ask(key, serve_above=self.serve_above,  # noqa: E731
                                      cheap_above=min(0.6, self.serve_above))
        try:
            if self.latency_budget_ms is None:
                hit = call()
            else:
                hit = _LOOKUPS.submit(call).result(timeout=self.latency_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.counts["lookup_timeouts"] += 1
            return None
        except Exception:  # noqa: BLE001 - an unreachable cache means "ask the model"
            self.counts["lookup_errors"] += 1
            return None
        if hit.get("route") == "cache" and hit.get("answer"):
            return hit["answer"]
        return None

    @staticmethod
    def _norm(text: str) -> str:
        return " ".join((text or "").lower().strip(_TRIM).split())

    def stats(self) -> dict:
        return dict(self.counts)


__all__ = ["CallSession", "TurnResult", "FILLER", "MODES"]
