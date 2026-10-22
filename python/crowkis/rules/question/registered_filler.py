"""The RegisteredFiller rule (stage 1, question; operational)."""

from __future__ import annotations

from typing import Mapping, Optional

from ...runtime.stats import Counter
from ...turns.verdict import Verdict
from ...turns.voice_turn import VoiceTurn
from ...understanding.word_rules import _normalise

FILLER_ROUTE = "filler"
FILLER_REASON = "registered filler, answered without a lookup or a model"


class RegisteredFiller:
    """A turn the app registered a filler for ("hello") is answered with it at once: no lookup and
    no model. ``fillers`` is the session's own map (normalised trigger to reply), read live, so
    fillers registered later count."""

    name = "RegisteredFiller"
    floor = False

    def __init__(self, fillers: Mapping[str, str]) -> None:
        self._fillers = fillers

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        filler = self._fillers.get(_normalise(turn.text))
        if filler is None:
            return None
        return Verdict(self.name, FILLER_REASON, (Counter.FILLED,), route=FILLER_ROUTE, answer=filler)
