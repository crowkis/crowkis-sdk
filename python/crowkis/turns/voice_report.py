"""VoiceReport: a voice call's decisions and outcomes, as TurnCore's Report and EarlyAnswers."""

from __future__ import annotations

import logging
from typing import Optional

from ..runtime.stats import Counter, Stats
from .checked import Checked, LookedUp
from .decision import TurnDecision, _Outcome
from .turn_host import TurnHost
from .verdict import Verdict

_LOG = logging.getLogger("crowkis")
SERVED_REASON = "confident cache hit"


class VoiceReport:
    """Adapter: what TurnCore found, as a voice call reports it: a ``TurnDecision`` for a turn and an
    ``_Outcome`` for an answer, counted in ``Stats``. A served turn joins the transcript and carries
    its audio when the session caches audio. A rule that answered the turn itself (a filler) is the
    only early answer voice has."""

    def __init__(self, host: TurnHost, stats: Stats) -> None:
        self._host = host
        self._stats = stats

    def before_reading(self, said: str) -> None:
        """Voice reads every turn first (its fillers are checked once the turn is read)."""
        return None

    def after_check(self, checked: Checked) -> Optional[TurnDecision]:
        """A registered filler answers the turn at once (its audio may be shared)."""
        verdict = checked.objection
        if verdict.answer is None:
            return None
        self._count(verdict)
        decision = TurnDecision(verdict.route, text=verdict.answer, audio=self._host.voiced(verdict.answer),
                                confidence=1.0, reason=verdict.reason, rule=verdict.rule)
        decision._audio_shareable = True
        return decision

    def to_model(self, checked: Checked) -> TurnDecision:
        return self._infer(checked.objection)

    def missed(self, checked: Checked, looked: LookedUp) -> TurnDecision:
        return self._infer(looked.objection, confidence=looked.hit["confidence"] if looked.hit else 0.0)

    def served(self, checked: Checked, looked: LookedUp) -> TurnDecision:
        turn, cached = checked.subject, looked.cached
        self._stats.add(Counter.SERVED)
        self._host.transcript.append({"role": "user", "content": turn.said})
        self._host.transcript.append({"role": "assistant", "content": cached.answer})
        decision = TurnDecision(
            "serve",
            text=cached.answer,
            audio=self._host.voiced(cached.answer, cacheable=not turn.is_personal),
            confidence=looked.hit["confidence"],
            reason=SERVED_REASON,
        )
        decision._audio_shareable = not turn.is_personal
        return decision

    def kept(self, verdict: Verdict) -> _Outcome:
        """A save rule (or the pairing) kept the answer out of the shared cache."""
        self._count(verdict)
        return _Outcome(verdict.outcome, verdict.reason, rule=verdict.rule)

    def refused(self, error: Exception) -> _Outcome:
        self._stats.add(Counter.LEARN_ERRORS)
        why = f"the server refused the write: {str(error) or type(error).__name__}"
        _LOG.warning("crowkis voice answer not stored, %s", why)
        return _Outcome("refused", why, rule="WriteRefused")

    def _infer(self, verdict: Verdict, *, confidence: float = 0.0) -> TurnDecision:
        """The model answers this turn: ``verdict`` says which rule decided so, and why."""
        self._count(verdict)
        self._stats.count_rule(verdict.rule)
        return TurnDecision("infer", confidence=confidence, reason=verdict.reason, rule=verdict.rule)

    def _count(self, verdict: Verdict) -> None:
        for counter in verdict.counts:
            self._stats.add(counter)
