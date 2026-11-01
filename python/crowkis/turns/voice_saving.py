"""VoiceSaving: the save check and the write of a voice call's answers, as TurnCore's Saving."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Protocol

from ..runtime.bounded_writer import BoundedWriter
from ..runtime.write_result import WriteResult
from ..runtime.stats import Counter, Stats
from ..state.call_state import CallState
from ..understanding.word_rules import (
    _AMOUNT_WORDS,
    _EMAIL,
    _MATTERS,
    _SLOT,
    _abstract,
    _carries_call_context,
    _has_digit,
    _identifies,
    _leaks,
    _reads_out_digits,
    _words,
)
from .answered import VoiceAnswered
from .checked import Checked
from .model_answer import ModelAnswer
from .outcome import Outcome, RecordedOutcome
from .session_call import SessionCall
from .voice_report import VoiceReport

if TYPE_CHECKING:
    from ..rules.rule_set import RuleSet


class VoiceSessionSaves(Protocol):
    """What VoiceSaving reads of the voice session, live: an app may change these between turns."""

    agent: Any
    latency_budget_ms: Optional[float]
    ttl: Optional[int]
    share_templates: bool
    values: Dict[str, str]
    transcript: List[Dict[str, str]]


class VoiceSaving:
    """check(): the answer as the save rules read it: ``answer_given`` first, then, once it is known
    to be an answer, its cache key and its place in the transcript, then ``before_sharing``.
    write(): the shared form of the answer and its write (the writer's boundary turns a failed one into
    the ``refused`` outcome): a personal
    answer only as a shape with this call's values taken out (``personal``, and only when the session
    shares templates), any other after the ``sharing`` rules; through the bounded write (in the
    call's ``segment``, if any), with the question it was saved for. ``last_stored`` is the question
    the latest shared answer was stored under."""

    def __init__(self, session: VoiceSessionSaves, *, rules: "RuleSet", call: SessionCall,
                 state: CallState, report: VoiceReport, writer: BoundedWriter, stats: Stats,
                 segment: Optional[str]) -> None:
        self._session = session
        self._rules = rules
        self._call = call
        self._state = state
        self._report = report
        self._writer = writer
        self._stats = stats
        self._segment = segment
        self.last_stored: Optional[str] = None

    def check(self, answered: VoiceAnswered) -> Checked:
        answer = ModelAnswer(answered.said, answered.model_said, None, self._call, private=answered.private,
                             instructions=answered.instructions,
                             cacheable=answered.shareable and not answered.private)
        verdict = self._rules.answer_given.first_objection(answer)
        if verdict is not None:
            return Checked(answer, verdict)
        answer = answer.keyed(self._state.rewritten_for(answer.text)
                              or self._call.context_key(answered.said, answer.text))
        self._session.transcript.append({"role": "user", "content": answered.said})
        self._session.transcript.append({"role": "assistant", "content": answered.model_said})
        return Checked(answer, self._rules.before_sharing.first_objection(answer))

    def write(self, answer: ModelAnswer) -> RecordedOutcome:
        if answer.is_personal:
            return self._write_personal(answer)
        verdict = self._rules.sharing.first_objection(answer)
        if verdict is not None:
            return self._report.kept(verdict)
        written = self._learn(answer.key, answer.answer, ttl=self._session.ttl)
        if written.refused:
            return self._report.refused(written.error)
        if not (written.objection and written.objection.rule == "NotStored"):
            self.last_stored = answer.key  # a key the server kept nothing under is not waited for
        if not written.written:  # a slow server gets no extra write
            return self._report.kept(written.objection)
        self._call.question_records().keep(answer.key, answer.answer, self._session.ttl)
        return RecordedOutcome(Outcome.SAVED)

    def _learn(self, *args: Any, **kwargs: Any) -> WriteResult:
        """agent.learn(), waited for no longer than twice the latency budget (BoundedWriter); without
        a budget it is waited for, as it always was. Not written in time: the ``slow_write`` verdict
        to report (still running, or not written at all because too many writes wait on a slow
        server); failed: refused."""
        if self._segment:
            kwargs.setdefault("segment", self._segment)
        return self._writer.write_within(self._session.agent.learn, *args,
                                         budget_ms=self._session.latency_budget_ms, **kwargs)

    def _write_personal(self, answer: ModelAnswer) -> RecordedOutcome:
        """A personal answer is shared only as a shape with this call's values taken out."""
        personal = self._rules.personal
        verdict = personal.check(answer)
        if verdict is None:
            templated = self._learn_personal(answer.key, answer.answer)
            if templated is None:
                verdict = personal.refusal()
            elif templated.written:
                return RecordedOutcome(Outcome.TEMPLATE)
            elif templated.refused:
                return self._report.refused(templated.error)
            else:
                verdict = templated.objection  # slow_write: the shape was not confirmed written
        return self._report.kept(verdict)

    def _learn_personal(self, keyed: str, model_said: str) -> Optional[WriteResult]:
        """Store a personal answer as a shape: what the write did, or None (nothing written) when it
        cannot be made generic, or when this session does not share templates."""
        session = self._session
        if not session.share_templates:
            self._stats.add(Counter.UNCACHEABLE_PERSONAL)
            return None
        shaped = _abstract(model_said, session.values)
        # The model read the whole call: what is left outside the slots must say nothing
        # of this caller that was not declared (a name, an address, a number, a matter).
        outside = _SLOT.sub(" ", shaped)
        words = _words(outside)
        earlier = [turn["content"] or "" for turn in session.transcript if turn["role"] == "user"]
        undeclared = (
            any(_has_digit(w) or w in _AMOUNT_WORDS or w in _MATTERS for w in words)
            or _reads_out_digits(outside, words) or bool(_EMAIL.search(outside)) or _identifies(outside, words)
            or _carries_call_context(outside, keyed, earlier)
        )
        if (
            session.values
            and _SLOT.search(shaped)
            and not _leaks(shaped, session.values)
            and not undeclared
        ):
            return self._learn(keyed, shaped, ttl=session.ttl, template=True)
        self._stats.add(Counter.UNCACHEABLE_PERSONAL)
        return None
