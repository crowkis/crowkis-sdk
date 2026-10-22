"""Question rules about turns too short or too broken to match on meaning."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...understanding.word_rules import _unfinished


class TooShort:
    """A turn too short to match on meaning ("thank you") is not looked up, unless short
    turns are on and the server's decision engine vouches for what it caches."""

    name = "TooShort"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not turn.is_short or (turn.call.short_turns and turn.call.engine_vouches()):
            return None
        return Verdict(self.name, "transcript too short to match safely", ("refused_short",))


class CutOff:
    """A cut-off question ("do you deliver on") is close in meaning to a full one but asks
    something else: never served a stored answer, never stored."""

    name = "CutOff"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not _unfinished(turn.text):
            return None
        return Verdict(self.name, "the turn was cut off mid-question", ("refused_short",))
