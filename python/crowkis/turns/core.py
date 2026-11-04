"""TurnCore: one turn of any channel, from what the caller said to a result, and from the model's
answer to what is shared; and the step interfaces it calls."""

from __future__ import annotations

import time
from typing import Any, Dict, Optional, Protocol

from ..runtime.cache_lookup import CacheLookup
from .values import Checked, LookedUp, Verdict

class CallSettings(Protocol):
    """The call's settings a lookup reads, live: an app may change them between turns."""

    @property
    def agent(self) -> Any:
        """The agent lookups go through."""

    @property
    def serve_above(self) -> float:
        """The confidence a cached answer needs to be served."""

    @property
    def latency_budget_ms(self) -> Optional[float]:
        """The lookup's budget (None: wait as long as the cache takes)."""


class Pairing(Protocol):
    """Which turn an answer belongs to."""

    def open(self) -> int:
        """A turn is being decided: its number."""

    def settle(self, answered: Any) -> Checked:
        """The answer paired with its turn, or the objection that drops it (the caller moved on)."""


class EarlyAnswers(Protocol):
    """Answers a turn gets without the cache or the model."""

    def before_reading(self, said: str, turn: int) -> Optional[Any]:
        """The channel's result for turn number ``turn``, answered before it is read, or None."""

    def after_check(self, checked: Checked) -> Optional[Any]:
        """The channel's result for a turn the question check stopped and something other than the
        model answers (a filler, an app's hook), or None."""


class TurnReader(Protocol):
    """How a turn is understood."""

    def read(self, said: str, turn: int) -> Any:
        """Turn number ``turn``, read: what the question and hit checks see."""


class QuestionCheck(Protocol):
    """Stage 1: whether a turn may be looked up and shared."""

    def check_question(self, turn: Any) -> Checked:
        """The turn as checked (keyed, for a chat) and the first objection, if any."""


class HitCheck(Protocol):
    """Stage 2: whether a hit may be served."""

    def check_hit(self, turn: Any, hit: Dict[str, Any], started: float) -> Checked:
        """The hit as the hit rules read it and the objection to serving it, if any."""


class Report(Protocol):
    """Adapter: the channel's public results, counts and events for what the core found."""

    def to_model(self, checked: Checked) -> Any:
        """The question check stopped the turn: the model answers with the whole call."""

    def missed(self, checked: Checked, looked: LookedUp) -> Any:
        """No hit may be served: the model answers the turn."""

    def served(self, checked: Checked, looked: LookedUp) -> Any:
        """A hit is served (``looked.cached``)."""

    def kept(self, verdict: Verdict) -> Any:
        """An answer is not saved (dropped or kept out of the shared cache): the outcome."""

    def recorded(self, answered: Any, outcome: Any) -> Any:
        """Whatever happened to an answer: counted or reported as the channel does; the outcome."""


class Saving(Protocol):
    """Stage 3 and the write."""

    def check(self, answered: Any) -> Checked:
        """The answer as the save rules read it, and the objection to saving it, if any."""

    def write(self, answer: Any) -> Any:
        """Share the answer and write it, within the bounded write: the outcome."""


# The confidence above which the agent may route a hit to a cheaper model (capped by serve_above).
CHEAP_ABOVE = 0.60


class TurnCore:
    """Template Method: the fixed steps of a turn. decide(): open (number) the turn, answers before
    reading, read it, the question check, an early answer, the lookup inside the budget, the hit check,
    serve or hand to the model. record(): pair the answer with its turn, the save check, the write
    (a failed write comes back from the writer's boundary as an outcome), then the channel notes what
    was recorded.

    What differs between channels is injected (see ``turn_steps``); the facades pick the parts.
    ``settings`` is the call's live settings (agent, serve_above, latency_budget_ms)."""

    def __init__(self, settings: CallSettings, *, pairing: Pairing, answers: EarlyAnswers, reader: TurnReader,
                 question_check: QuestionCheck, cache_lookup: CacheLookup, hit_check: HitCheck, report: Report,
                 saving: Saving) -> None:
        self._settings = settings
        self._pairing = pairing
        self._answers = answers
        self._reader = reader
        self._question_check = question_check
        self._cache_lookup = cache_lookup
        self._hit_check = hit_check
        self._report = report
        self._saving = saving

    def decide(self, said: str) -> Any:
        """The channel's result for this turn: an early answer, a cached answer, or the model's turn."""
        turn = self._pairing.open()
        early = self._answers.before_reading(said, turn)
        if early is not None:
            return early
        checked = self._question_check.check_question(self._reader.read(said, turn))
        if checked.objection is not None:
            answered = self._answers.after_check(checked)
            return answered if answered is not None else self._report.to_model(checked)
        looked = self.look_up(checked.subject)
        if looked.objection is not None:
            return self._report.missed(checked, looked)
        return self._report.served(checked, looked)

    def look_up(self, turn: Any) -> LookedUp:
        """The cache's hit for a turn's key, within the budget, and the hit check's word on it."""
        settings = self._settings
        ask = lambda: settings.agent.ask(  # noqa: E731 - evaluated on the lookup's thread, inside the budget
            turn.key,
            serve_above=settings.serve_above,
            cheap_above=min(CHEAP_ABOVE, settings.serve_above),
            **turn.lookup_options,
        )
        started = time.monotonic()
        hit, objection = self._cache_lookup.find(ask, started, settings.latency_budget_ms)
        if objection is not None:
            return LookedUp(hit, objection=objection)
        found = self._hit_check.check_hit(turn, hit, started)
        return LookedUp(hit, found.subject, found.objection)

    def record(self, answered: Any) -> Any:
        """What happens to the model's answer: dropped when the caller moved on, kept out of the shared
        cache by a save rule, or shared. Never raises for the write: a refused write (security
        pipeline, tenant limit, cache down) must not end a call; the channel reports it."""
        paired = self._pairing.settle(answered)
        if paired.objection is not None:
            return self._report.recorded(answered, self._report.kept(paired.objection))
        checked = self._saving.check(paired.subject)
        if checked.objection is not None:
            return self._report.recorded(answered, self._report.kept(checked.objection))
        return self._report.recorded(answered, self._saving.write(checked.subject))
