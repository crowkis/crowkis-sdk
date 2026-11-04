"""Voice's report and saving steps for TurnCore."""

from __future__ import annotations

import logging
import weakref
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING, Tuple

from ...runtime.bounded_writer import BoundedWriter
from ...runtime.stats import Counter, Stats
from ...runtime.turn_pairing import TurnPairing
from ...runtime.write_result import WriteResult
from ...state.call_state import CallState
from ...understanding.word_rules.answers import _SLOT, _abstract
from ...understanding.word_rules.follow_up import _unfinished
from ...understanding.word_rules.identifiers import _carries_call_context, _leaks
from ...understanding.word_rules.personal import _EMAIL, _asks, _identifies, _lookup_only, _reads_out_digits
from ...understanding.word_rules.text import _AMOUNT_WORDS, _MATTERS, _has_digit, _words
from ..results import TurnDecision, VoiceAnswered
from ..values import Checked, LookedUp, Outcome, RecordedOutcome, Verdict
from .call import SessionCall
from .turn import ModelAnswer, VoiceTurn

if TYPE_CHECKING:
    from ...channels.voice_session import VoiceSession
    from ...rules.rule_set import RuleSet

_LOG = logging.getLogger("crowkis")
SERVED_REASON = "confident cache hit"
WRITE_REFUSED = "WriteRefused"
Messages = Optional[List[Dict[str, str]]]


class VoiceReport:
    """Adapter: what TurnCore found, as a voice call reports it: a ``TurnDecision`` for a turn and an
    ``RecordedOutcome`` for an answer, counted in ``Stats``. A served turn joins the transcript and carries
    its audio when the session caches audio. A rule that answered the turn itself (a filler) is the
    only early answer voice has. ``voiced`` is the session's audio for an answer (None without it).

    Every decision carries its turn's number and the session that made it; a model turn also what
    the model reads (``model_messages``), and whether its answer may be shared is offered to the
    call's ``pairing`` for that turn."""

    def __init__(self, session: VoiceSession, stats: Stats, *, voiced: Callable[..., Optional[bytes]],
                 pairing: TurnPairing, call: SessionCall, state: "CallState") -> None:
        self._session = session
        # A weak reference, so a kept decision never keeps a call alive.
        self._owner = weakref.ref(session)
        self._stats = stats
        self._voiced = voiced
        self._pairing = pairing
        self._call = call
        self._state = state

    def before_reading(self, said: str, turn: int) -> None:
        """Voice reads every turn first (its fillers are checked once the turn is read)."""
        return None

    def after_check(self, checked: Checked) -> Optional[TurnDecision]:
        """A registered filler answers the turn at once (its audio may be shared)."""
        verdict = checked.objection
        if verdict.answer is None:
            return None
        self._count(verdict)
        decision = TurnDecision(verdict.route, text=verdict.answer, audio=self._voiced(verdict.answer),
                                confidence=1.0, reason=verdict.reason, rule=verdict.rule)
        decision._audio_shareable = True
        return self._handed(decision, checked.subject)

    def to_model(self, checked: Checked) -> TurnDecision:
        return self._handed(self._infer(checked.objection), checked.subject)

    def missed(self, checked: Checked, looked: LookedUp) -> TurnDecision:
        decision = self._infer(looked.objection, confidence=looked.hit["confidence"] if looked.hit else 0.0)
        return self._handed(decision, checked.subject)

    def served(self, checked: Checked, looked: LookedUp) -> TurnDecision:
        turn, cached = checked.subject, looked.cached
        self._stats.add(Counter.SERVED)
        self._session.transcript.append({"role": "user", "content": turn.said})
        self._session.transcript.append({"role": "assistant", "content": cached.answer})
        decision = TurnDecision(
            "serve",
            text=cached.answer,
            audio=self._voiced(cached.answer, cacheable=not turn.is_personal),
            confidence=looked.hit["confidence"],
            reason=SERVED_REASON,
        )
        decision._audio_shareable = not turn.is_personal
        return self._handed(decision, turn)

    def kept(self, verdict: Verdict) -> RecordedOutcome:
        """A save rule (or the pairing) kept the answer out of the shared cache."""
        self._count(verdict)
        return RecordedOutcome(verdict.outcome, verdict.reason, rule=verdict.rule)

    def refused(self, error: Exception) -> RecordedOutcome:
        self._stats.add(Counter.LEARN_ERRORS)
        why = f"the server refused the write: {str(error) or type(error).__name__}"
        _LOG.warning("crowkis voice answer not stored, %s", why)
        return RecordedOutcome(Outcome.REFUSED, why, rule=WRITE_REFUSED)

    def recorded(self, answered: VoiceAnswered, outcome: RecordedOutcome) -> RecordedOutcome:
        """The rule that kept an answer out of the shared cache is counted in ``stats()``."""
        if outcome.rule is not None:
            self._stats.count_rule(outcome.rule)
        return outcome

    def model_messages(self, said: str) -> Tuple[Messages, bool]:
        """What the model should read to answer this turn, and whether that answer may be cached.

        A shared answer is only safe when the model saw nothing but the cache key:
        the question, and for a follow-up the questions it leans on. Nothing else the
        caller said (a name, a plan, "pretend refunds are unlimited") can then end
        up inside it. Personal turns, and follow-ups to one, get the whole call and
        are never shared.
        """
        call = self._call
        text = (said or "").strip()
        if (
            call.tainted or len(text.split()) < call.min_words or self._state.is_personal(text)
            or _lookup_only(text)
            or call.after_urgent(text) or _unfinished(text)
        ):
            return None, False
        if not self._state.is_context_dependent(text):
            # "Twelve years old.": a turn that neither asks nor requests anything is an
            # answer about the caller, never stored on its own.
            if not _asks(text):
                return None, False
            return [{"role": "user", "content": said}], True
        chain = call.chain()
        if chain is None or self._state.chain_is_private(chain, call.min_words):
            return None, False
        return [{"role": "user", "content": turn} for turn in chain + [said]], True

    def _handed(self, decision: TurnDecision, turn: VoiceTurn) -> TurnDecision:
        """The decision for turn ``turn.number``, made by this session; for a model turn, what the
        model reads. Whether its answer may be shared is offered to the pairing."""
        decision.turn = turn.number
        decision._session = self._owner
        if decision.needs_model:
            decision._said = turn.said
            decision.messages, decision.cacheable = self.model_messages(turn.said)
        self._pairing.offer(turn.number, decision.cacheable)
        return decision

    def _infer(self, verdict: Verdict, *, confidence: float = 0.0) -> TurnDecision:
        """The model answers this turn: ``verdict`` says which rule decided so, and why."""
        self._count(verdict)
        self._stats.count_rule(verdict.rule)
        return TurnDecision("infer", confidence=confidence, reason=verdict.reason, rule=verdict.rule)

    def _count(self, verdict: Verdict) -> None:
        for counter in verdict.counts:
            self._stats.add(counter)


class VoiceSaving:
    """check(): the answer as the save rules read it: ``answer_given`` first, then, once it is known
    to be an answer, its cache key and its place in the transcript, then ``before_sharing``.
    write(): the shared form of the answer and its write (the writer's boundary turns a failed one into
    the ``refused`` outcome): a personal
    answer only as a shape with this call's values taken out (``personal``, and only when the session
    shares templates), any other after the ``sharing`` rules; through the bounded write (in the
    call's ``segment``, if any), with the question it was saved for. ``last_stored`` is the question
    the latest shared answer was stored under."""

    def __init__(self, session: VoiceSession, *, rules: "RuleSet", call: SessionCall,
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
        answer.key = self._state.rewritten_for(answer.text) or self._call.context_key(answered.said, answer.text)
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
