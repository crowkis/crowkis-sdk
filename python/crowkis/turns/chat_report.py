"""ChatReport: a chat's results, outcomes, counts and events, as TurnCore's Report."""

from __future__ import annotations

from typing import Any, Dict, List, Protocol

from ..state.call_state import CallState
from .chat_turns import ChatTurns
from .checked import Checked, LookedUp
from .routes import SHARED
from .turn_result import Message, TurnResult
from .verdict import Verdict

HIT_REASON = "cache hit"
MISS_REASON = "cache miss"
WRITE_FAILED = "refused:write_failed"
SAVE_REFUSED = "save_refused"


class ChatSessionReports(Protocol):
    """What ChatReport reads of the chat, live."""

    state: CallState
    counts: Dict[str, int]

    def emit(self, event: Dict[str, Any]) -> None:
        """Send a monitoring event (never raises)."""


class ChatReport:
    """Adapter: what TurnCore found, as a chat reports it: a ``TurnResult`` for a turn (one the agent
    must answer awaits it in ``ChatTurns``), an outcome string for an answer, the ``counts`` each
    verdict names, a "turn" event, and the agent's reply noted in the chat's state when it is
    already known (a hit)."""

    def __init__(self, session: ChatSessionReports, turns: ChatTurns) -> None:
        self._session = session
        self._turns = turns

    def to_model(self, checked: Checked) -> TurnResult:
        reading = checked.subject
        self._session.emit(dict(self._event(reading), hit=False))
        return self._turns.await_answer(TurnResult(self._turns.deciding, reading.verdict.route, frame=reading.frame,
                                                   verdict=reading.verdict, reason=";".join(reading.verdict.reasons)))

    def missed(self, checked: Checked, looked: LookedUp) -> TurnResult:
        reading = checked.subject
        self.count(looked.objection)
        self._session.emit(dict(self._event(reading), hit=False))
        return self._turns.await_answer(TurnResult(self._turns.deciding, SHARED, frame=reading.frame,
                                                   verdict=reading.verdict, messages=self._messages(reading),
                                                   reason=MISS_REASON))

    def served(self, checked: Checked, looked: LookedUp) -> TurnResult:
        reading, answer = checked.subject, looked.hit["answer"]
        self._session.counts["hits"] += 1
        result = TurnResult(self._turns.deciding, SHARED, text=answer, needs_model=False, frame=reading.frame,
                            verdict=reading.verdict, reason=HIT_REASON)
        self._session.state.note_agent_reply(answer)
        self._session.emit(dict(self._event(reading), hit=True))
        return self._turns.await_answer(result)

    def kept(self, verdict: Verdict) -> str:
        self.count(verdict)
        return verdict.outcome

    def refused(self, error: Exception) -> str:
        self._session.counts[SAVE_REFUSED] += 1
        return WRITE_FAILED

    def count(self, verdict: Verdict) -> None:
        """Add to the counters ``verdict`` names."""
        counts = self._session.counts
        for name in verdict.counts:
            counts[name] = counts.get(name, 0) + 1

    def _messages(self, reading: Any) -> List[Message]:
        """What the model reads for a shared question: the question alone, with the attributes in its
        key and the reply language as a system note."""
        verdict = reading.verdict
        messages = [{"role": "user", "content": verdict.question}]
        notes = []
        if verdict.attributes:
            notes.append("Answer for: " + "; ".join(f"{k}: {v}" for k, v in sorted(verdict.attributes.items())) + ".")
        language = self._session.state.language or reading.frame.language
        if language:
            notes.append(f"Reply in this language: {language}.")
        if notes:
            messages.insert(0, {"role": "system", "content": " ".join(notes)})
        return messages

    def _event(self, reading: Any) -> Dict[str, Any]:
        verdict, frame = reading.verdict, reading.frame
        return {"type": "turn", "turn_id": self._turns.deciding, "route": verdict.route,
                "reasons": list(verdict.reasons), "shared": verdict.shared, "urgent": frame.urgent,
                "kind": frame.kind, "confidence": frame.confidence, "question": verdict.question,
                "key": verdict.key, "question_type": frame.question_type if verdict.shared else None}
