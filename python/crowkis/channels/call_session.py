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
import re
import string
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from ..state.call_state import IDENTITIES, CallState
from ..rules.chat_rule_set import ChatRuleSet
from ..runtime.cache_lookup import CacheLookup
from ..runtime.bounded_writer import BoundedWriter
from ..runtime.question_records import QuestionRecords
from . import voice_session as _voice
from ..turns.values import CHAT
from ..rules.question import UrgentWords
from ..turns.results import ChatAnswered
from ..turns.chat.steps import ChatAnswers, call_hook
from ..turns.chat.checks import ChatHitCheck
from ..turns.chat.checks import ChatQuestionCheck
from ..turns.chat.turn import ChatReader
from ..turns.chat.turn import ChatReading
from ..turns.chat.steps import ChatReport
from ..turns.chat.steps import ChatSaving
from ..turns.chat.steps import ChatTurns
from ..turns.core import TurnCore
from ..turns.results import FILLER  # noqa: F401 - re-exported
from ..turns.results import TurnResult  # noqa: F401 - re-exported
from ..understanding.chat_details import _norm
from ..understanding.word_rules.call_context import _instructs, _tells_about_caller
from ..understanding.word_rules.phrases import _PII_PLACEHOLDER
from ..understanding.word_rules.text import _proper_nouns, _words
from ..understanding.turn_frame import TurnFrame
from ..understanding.understanders import ReplayUnderstander, Understander
from ..rules.rule_checker import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT, RuleChecker, Verdict







MODES = ("full", "replay_only", "off")
Message = Dict[str, str]
_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-call")
_UNDERSTAND = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-understand")
# A chat's counters for each way a lookup fails open.
_LOOKUP_DEADLINE_COUNTS = ("lookup_timeouts",)
_LOOKUP_UNAVAILABLE_COUNTS = ("lookup_errors",)


# A first-person claim that something was done. A cached answer must never claim an action.




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
    ``instructions``  the system prompt the model reads with a shared question. A shared
                      answer that repeats a detail it gives about this caller ("Hi Asha!")
                      is never saved (``refused:prompt_detail``).
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
        urgent_reply: Optional[str] = None,
        on_tools: Optional[Callable[[str, TurnFrame], Optional[str]]] = None,
        instructions: str = "",
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
        # The business's pre-approved reply to an emergency (its helplines); without one the
        # model answers with the whole call. Never cached either way.
        self.urgent_reply = (urgent_reply or "").strip() or None
        # The business's own system for "my balance", "my booking": returns the reply, or None
        # for the model to answer with the whole call. Never cached.
        self.on_tools = on_tools
        self.instructions = (instructions or "").strip()
        self.mode = "full"
        self.set_mode(mode)
        self.state = CallState()
        # A chat: what it can do. This session keeps the chat's state, counts, settings and hooks.
        self.channel = CHAT
        self._fillers = {_norm(k): v for k, v in (fillers or {}).items()}
        self._shapes: Dict[str, _Shape] = {}
        self.counts: Dict[str, int] = {k: 0 for k in (
            URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT, FILLER, "hits", "saved", "save_refused",
            "lookup_timeouts", "lookup_errors", "understand_errors", "understand_timeouts", "fallback_used",
            "cancelled", "sharing_off", "tools_answered")}
        self._core = self._build_core()

    def _build_core(self) -> TurnCore:
        """The one TurnCore with a chat's parts (this session is their composition root). Its lookup
        serves a late hit, as Chat always did."""
        self._turns = ChatTurns()
        self._report = ChatReport(self, self._turns)
        records = QuestionRecords(self.agent, read_pool=_LOOKUPS, submit_write=_voice._submit_write)
        self._cache_lookup = CacheLookup(_LOOKUPS, refuse_late_hits=False, deadline_counts=_LOOKUP_DEADLINE_COUNTS,
                                         unavailable_counts=_LOOKUP_UNAVAILABLE_COUNTS)
        self._saving = ChatSaving(self, save_rules=ChatRuleSet.save_chain(), question_records=records,
                                  report=self._report,
                                  writer=BoundedWriter(_voice._WRITES, lambda: _voice._WRITES_MAX, self._count_write,
                                                       _voice._LOG))
        question_check = ChatQuestionCheck(self, shared_question_rules=ChatRuleSet.shared_question_chain(),
                                           urgent_words=UrgentWords())
        hit_check = ChatHitCheck(self, hit_rules=ChatRuleSet.hit_chain(), question_records=records)
        return TurnCore(self, pairing=self._turns, answers=ChatAnswers(self, self._turns),
                        reader=ChatReader(self, _UNDERSTAND), question_check=question_check,
                        cache_lookup=self._cache_lookup, hit_check=hit_check, report=self._report, saving=self._saving)

    def set_mode(self, mode: str) -> None:
        """Switch sharing at runtime: "full", "replay_only" (no model) or "off" (share nothing)."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        self.mode = mode

    # --- one caller turn --------------------------------------------------------------


    def handle(self, turn: str) -> TurnResult:
        return self._core.decide(turn)

    def record_answer(self, result: TurnResult, answer: str, *, mentions: tuple = (),
                      task: Optional[str] = None, private: bool = False) -> str:
        return self._core.record(ChatAnswered(result, answer, mentions, task, private))



    # --- personal answers: phrasing a verified value, never fetching or deciding it -----

    def cancel(self) -> bool:
        """Barge-in: the open turn is abandoned and its answer will never be saved."""
        return self._turns.cancel()

    def save_check(self, answer: str, verdict: Verdict, frame: Optional[TurnFrame] = None,
                   private: bool = False) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        return self._saving.save_check(answer, verdict, frame, private)

    def _count_write(self, counter: Any) -> None:
        """A slow or late-failing write, counted under its name (BoundedWriter's counters)."""
        name = getattr(counter, "value", str(counter))
        self.counts[name] = self.counts.get(name, 0) + 1

    def emit(self, event: Dict[str, Any]) -> None:
        """Send a monitoring event (never raises)."""
        if self.on_event is not None:
            call_hook(self.on_event, event)

    def _lookup(self, key: str, segment: Optional[str]) -> Optional[str]:
        """The cached answer for a shared key, or None (kept for code that calls it; TurnCore looks up)."""
        looked = self._core.look_up(ChatReading("").checked_as(Verdict(True, SHARED, key=key, segment=segment)))
        if looked.objection is not None:
            self._report.count(looked.objection)
            return None
        return looked.hit["answer"]

    @property
    def fillers(self) -> Dict[str, str]:
        """Registered fillers, by normalised trigger."""
        return self._fillers

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


    def prompt_key(self) -> tuple:
        """Which system prompts this call's is compared with: the same agent's on the same
        channel (a chat's prompt never stands in for a voice call's)."""
        agent = self.agent
        tenant = getattr(agent, "tenant", None) or getattr(getattr(agent, "_client", None), "tenant", None)
        return (tenant, getattr(agent, "agent_id", None), getattr(self.checker, "channel", None))

    # --- saved with the chat thread ----------------------------------------------------------

    def export(self) -> Dict[str, Any]:
        """The thread's memory for the app's store, between turns. No transcript is in it."""
        return {"version": 1, "state": self.state.to_dict(), "next_turn": self._turns.next_turn}

    @classmethod
    def restore(cls, agent: Any, understander: Understander, data: Optional[Dict[str, Any]],
                **options: Any) -> "CallSession":
        """A session for the next turn of a thread saved with ``export``. Missing or damaged
        data starts a fresh thread; it never raises."""
        session = cls(agent, understander, **options)
        data = data if isinstance(data, dict) else {}
        session.state = CallState.from_dict(data.get("state"))
        try:
            session._turns.next_turn = max(1, int(data.get("next_turn", 1)))
        except (TypeError, ValueError, OverflowError):
            pass
        return session

    def stats(self) -> dict:
        return dict(self.counts)


__all__ = ["CallSession", "TurnResult", "FILLER", "MODES"]
