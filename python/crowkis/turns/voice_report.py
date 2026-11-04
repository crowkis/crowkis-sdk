"""VoiceReport: a voice call's decisions and outcomes, as TurnCore's Report and EarlyAnswers."""

from __future__ import annotations

import logging
import weakref
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Tuple

from ..runtime.stats import Counter, Stats
from ..runtime.turn_pairing import TurnPairing
from ..understanding.word_rules import _asks, _lookup_only, _unfinished
from .answered import VoiceAnswered
from .checked import Checked, LookedUp
from .decision import TurnDecision
from .outcome import Outcome, RecordedOutcome
from .verdict import Verdict
from .session_call import SessionCall
from .voice_turn import VoiceTurn

if TYPE_CHECKING:
    from ..channels.voice_session import VoiceSession
    from ..state.call_state import CallState

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
