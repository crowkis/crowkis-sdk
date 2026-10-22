"""The CutOff rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...understanding.word_rules import _unfinished
from ...runtime.stats import Counter


class CutOff:
    """A cut-off question ("do you deliver on") is close in meaning to a full one but asks
    something else: never served a stored answer, never stored."""

    name = "CutOff"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not _unfinished(turn.text):
            return None
        return Verdict(self.name, "the turn was cut off mid-question", (Counter.REFUSED_SHORT,))
