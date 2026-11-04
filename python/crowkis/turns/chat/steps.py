"""Chat's turn numbering, answers, report and saving steps for TurnCore."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Set, TYPE_CHECKING, Tuple

from ...rules.chain import RuleChain
from ...runtime.bounded_writer import BoundedWriter
from ...runtime.question_records import QuestionRecords
from ...state.call_state import CallState
from ...understanding.word_rules.chat import _masked, _norm
from ...understanding.model.frame import TurnFrame
from ..results import AGENT, ChatAnswered, FILLER, Message, PERSONAL, SHARED, TOOLS, TurnResult, URGENT
from ..values import Checked, LookedUp, Outcome, Verdict
from .turn import ChatAnswer

if TYPE_CHECKING:
    from ...channels.call_session import CallSession

CANCELLED_COUNT = "cancelled"
CANCELLED_VERDICT = Verdict("Cancelled", "the user talked over this turn", (CANCELLED_COUNT,),
                            outcome=Outcome.CANCELLED)
# An older turn finishing after a newer one started: never saved.
STALE_VERDICT = Verdict("Stale", "a newer turn awaits the answer", outcome=Outcome.STALE)


class ChatTurns:
    """Every turn gets the next number (``open``). A turn the agent must answer awaits it
    (``await_answer``); a filler, an urgent script or a tools answer does not, so the turn before
    it still does. An answer is paired only with the turn awaiting one, and never with a cancelled
    turn (a barge-in)."""

    def __init__(self) -> None:
        self.next_turn = 1
        self._awaiting: Optional[TurnResult] = None
        self._cancelled: Set[int] = set()

    def open(self) -> int:
        turn, self.next_turn = self.next_turn, self.next_turn + 1
        return turn

    def await_answer(self, result: TurnResult) -> TurnResult:
        """``result``'s turn is the one the agent's next answer belongs to."""
        self._awaiting = result
        return result

    def settle(self, answered: ChatAnswered) -> Checked:
        turn_id = answered.result.turn_id
        if turn_id in self._cancelled:
            return Checked(answered, CANCELLED_VERDICT)
        if self._awaiting is None or self._awaiting.turn_id != turn_id:
            return Checked(answered, STALE_VERDICT)
        self._awaiting = None
        return Checked(answered)

    def cancel(self) -> bool:
        """Barge-in: the turn awaiting an answer is abandoned and its answer will never be saved."""
        if self._awaiting is None:
            return False
        self._cancelled.add(self._awaiting.turn_id)
        self._awaiting = None
        return True


SHARING_OFF = "off"
URGENT_SCRIPT_REASON = "urgent script"
TOOLS_REASON = "answered by the business's tools"


def call_hook(hook: Callable[..., Any], *args: Any) -> Any:
    """Run an app hook; its result, or None when it fails."""
    try:
        return hook(*args)
    except Exception:  # noqa: BLE001 - an app hook must never end the chat
        return None


class ChatAnswers:
    """Before a turn is read: an empty turn goes to the agent, a registered filler answers it, and
    with sharing off the agent answers everything. After the check: the app's ``on_urgent`` hook
    runs on an urgent turn and its ``urgent_reply`` answers it; ``on_tools`` may answer a personal
    or live turn. None of these is ever cached; a hook that fails never ends the chat (``call_hook``)."""

    def __init__(self, session: CallSession, turns: ChatTurns) -> None:
        self._session = session
        self._turns = turns

    def before_reading(self, said: str, turn_id: int) -> Optional[TurnResult]:
        session = self._session
        text = " ".join((said or "").split())
        if not text:
            return self._turns.await_answer(TurnResult(turn_id, AGENT, reason="empty"))
        filler = session.fillers.get(_norm(text))
        if filler is not None:
            session.counts[FILLER] += 1
            session.state.note_agent_reply(filler)
            return TurnResult(turn_id, FILLER, text=filler, needs_model=False, reason="registered filler")
        if session.mode == SHARING_OFF:
            session.counts["sharing_off"] += 1
            result = self._turns.await_answer(TurnResult(turn_id, AGENT, reason="sharing off"))
            session.emit({"type": "turn", "turn_id": turn_id, "route": AGENT, "reasons": ["mode_off"],
                          "shared": False})
            return result
        return None

    def after_check(self, checked: Checked) -> Optional[TurnResult]:
        reading = checked.subject
        route = reading.verdict.route
        if route == URGENT:
            return self._urgent(reading)
        if route in (TOOLS, PERSONAL):
            return self._tools(reading)
        return None

    def _urgent(self, reading: Any) -> Optional[TurnResult]:
        session = self._session
        if session.on_urgent is not None:
            call_hook(session.on_urgent, reading.text, reading.frame)
        if not session.urgent_reply:
            return None
        session.state.note_agent_reply(session.urgent_reply)
        return TurnResult(reading.turn_id, URGENT, text=session.urgent_reply, needs_model=False,
                          frame=reading.frame, verdict=reading.verdict, reason=URGENT_SCRIPT_REASON)

    def _tools(self, reading: Any) -> Optional[TurnResult]:
        session = self._session
        if session.on_tools is None:
            return None
        answered = call_hook(session.on_tools, reading.text, reading.frame)
        if not answered:
            return None
        session.counts["tools_answered"] += 1
        session.state.note_agent_reply(_masked(answered))
        return TurnResult(reading.turn_id, reading.verdict.route, text=answered, needs_model=False,
                          frame=reading.frame, verdict=reading.verdict, reason=TOOLS_REASON)


HIT_REASON = "cache hit"
MISS_REASON = "cache miss"
WRITE_FAILED = Outcome.REFUSED.because("write_failed")
SAVE_REFUSED = "save_refused"


class ChatReport:
    """Adapter: what TurnCore found, as a chat reports it: a ``TurnResult`` for a turn (one the agent
    must answer awaits it in ``ChatTurns``), an outcome string for an answer, the ``counts`` each
    verdict names, a "turn" event (an "answer" event once recorded), and the agent's reply noted in the chat's state when it is
    already known (a hit)."""

    def __init__(self, session: CallSession, turns: ChatTurns) -> None:
        self._session = session
        self._turns = turns

    def to_model(self, checked: Checked) -> TurnResult:
        reading = checked.subject
        self._session.emit(dict(self._event(reading), hit=False))
        return self._turns.await_answer(TurnResult(reading.turn_id, reading.verdict.route, frame=reading.frame,
                                                   verdict=reading.verdict, reason=";".join(reading.verdict.reasons)))

    def missed(self, checked: Checked, looked: LookedUp) -> TurnResult:
        reading = checked.subject
        self.count(looked.objection)
        self._session.emit(dict(self._event(reading), hit=False))
        return self._turns.await_answer(TurnResult(reading.turn_id, SHARED, frame=reading.frame,
                                                   verdict=reading.verdict, messages=self._messages(reading),
                                                   reason=MISS_REASON))

    def served(self, checked: Checked, looked: LookedUp) -> TurnResult:
        reading, answer = checked.subject, looked.hit["answer"]
        self._session.counts["hits"] += 1
        result = TurnResult(reading.turn_id, SHARED, text=answer, needs_model=False, frame=reading.frame,
                            verdict=reading.verdict, reason=HIT_REASON)
        self._session.state.note_agent_reply(answer)
        self._session.emit(dict(self._event(reading), hit=True))
        return self._turns.await_answer(result)

    def kept(self, verdict: Verdict) -> str:
        self.count(verdict)
        return str(verdict.outcome)

    def refused(self, error: Exception) -> str:
        self._session.counts[SAVE_REFUSED] += 1
        return WRITE_FAILED

    def recorded(self, answered: ChatAnswered, outcome: str) -> str:
        """The "answer" event, whatever happened to the answer."""
        result = answered.result
        self._session.emit({"type": "answer", "turn_id": result.turn_id, "route": result.route, "outcome": outcome,
                            "key": result.verdict.key if result.verdict else None})
        return outcome

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
        return {"type": "turn", "turn_id": reading.turn_id, "route": verdict.route,
                "reasons": list(verdict.reasons), "shared": verdict.shared, "urgent": frame.urgent,
                "kind": frame.kind, "confidence": frame.confidence, "question": verdict.question,
                "key": verdict.key, "question_type": frame.question_type if verdict.shared else None}


SAVED_COUNT = "saved"
NOT_SHARED = Verdict("NotShared", "not a shared question the model answered", outcome=Outcome.NOT_SHARED)


class ChatSaving:
    """check(): the agent's reply is noted in the chat's state (names masked unless the question was
    shared); only the model's answer to a shared question may be saved, and only past the save rules.
    write(): ``agent.learn()``, waited for no longer than twice the latency budget (``BoundedWriter``,
    as voice; waited for without a budget; a failed write is ``report``'s refusal), then the question
    it was saved for is kept."""

    def __init__(self, session: CallSession, *, save_rules: RuleChain, writer: BoundedWriter,
                 question_records: QuestionRecords, report: ChatReport) -> None:
        self._session = session
        self._report = report
        self._save_rules = save_rules
        self._writer = writer
        self._question_records = question_records

    def check(self, answered: ChatAnswered) -> Checked:
        result, answer = answered.result, answered.answer
        kept = answer if result.route == SHARED else _masked(answer)
        self._session.state.note_agent_reply(kept, answered.mentions, answered.task)
        if result.route != SHARED or result.text is not None or result.verdict is None:
            return Checked(answered, NOT_SHARED)
        why = self.save_check(answer, result.verdict, result.frame, private=answered.private)
        if why:
            return Checked(answered, Verdict("SaveCheck", why, (SAVE_REFUSED,), outcome=Outcome.REFUSED.because(why)))
        return Checked(answered)

    def write(self, answered: ChatAnswered) -> str:
        verdict, answer = answered.result.verdict, answered.answer
        written = self._writer.write_within(self._session.agent.learn, verdict.key, answer, ttl=verdict.ttl,
                                            segment=verdict.segment, budget_ms=self._session.latency_budget_ms)
        if written.refused:
            return self._report.refused(written.error)
        if not written.written:
            return str(written.objection.outcome)
        self._session.counts[SAVED_COUNT] += 1
        self._question_records.keep(verdict.key, answer, verdict.ttl)
        return str(Outcome.SAVED)

    def save_check(self, answer: str, verdict: Any, frame: Optional[TurnFrame] = None,
                   private: bool = False) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        chat_answer = ChatAnswer(" ".join((answer or "").split()), verdict, frame, self._session.state,
                                 instructions=self._session.instructions, prompt_key=self._session.prompt_key(),
                                 private=private)
        objection = self._save_rules.first_objection(chat_answer)
        return None if objection is None else objection.reason
