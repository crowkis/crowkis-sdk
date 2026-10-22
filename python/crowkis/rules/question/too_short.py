"""The TooShort rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn


class TooShort:
    """A turn too short to match on meaning ("thank you") is not looked up, unless short
    turns are on and the server's decision engine vouches for what it caches."""

    name = "TooShort"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not turn.is_short or (turn.call.short_turns and turn.call.engine_vouches()):
            return None
        return Verdict(self.name, "transcript too short to match safely", ("refused_short",))
