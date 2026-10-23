"""TurnCore: one turn of any channel, from what the caller said to a result, and from the model's
answer to what is shared."""

from __future__ import annotations

import time
from typing import Any

from ..runtime.cache_lookup import CacheLookup
from .checked import LookedUp
from .turn_steps import CallSettings, EarlyAnswers, HitCheck, Pairing, QuestionCheck, Report, Saving, TurnReader

# The confidence above which the agent may route a hit to a cheaper model (capped by serve_above).
CHEAP_ABOVE = 0.60


class TurnCore:
    """Template Method: the fixed steps of a turn. decide(): open the turn, answers before reading,
    read it, the question check, an early answer, the lookup inside the budget, the hit check, serve
    or hand to the model. record(): pair the answer with its turn, the save check, the write (the one
    place a failed write becomes an outcome).

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
        self._pairing.open()
        early = self._answers.before_reading(said)
        if early is not None:
            return early
        checked = self._question_check.check_question(self._reader.read(said))
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
            return self._report.kept(paired.objection)
        checked = self._saving.check(paired.subject)
        if checked.objection is not None:
            return self._report.kept(checked.objection)
        try:
            return self._saving.write(checked.subject)
        except Exception as error:  # noqa: BLE001 - a refused write must not end a call
            return self._report.refused(error)
