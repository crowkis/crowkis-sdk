"""The OwnRecords rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...runtime.stats import Counter

OWN_RECORDS_REASON = (
    "the caller asked about their own records and this session has no "
    "values to fill a shared answer shape with, so nothing can be "
    "answered from cache without one caller's answer reaching the next"
)


class OwnRecords:
    """A question about the caller's own records ("where is my order 48213"), or another turn
    the word rules never share (urgent, identifying, unreadable), is never answered from the
    shared cache unless this call declared values to fill a shared answer shape with."""

    name = "OwnRecords"
    floor = True

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not turn.is_personal or turn.call.values:
            return None
        return Verdict(self.name, OWN_RECORDS_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
