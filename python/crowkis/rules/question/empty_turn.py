"""The EmptyTurn rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn


class EmptyTurn:
    """An empty transcript goes to the model."""

    name = "EmptyTurn"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if turn.text:
            return None
        return Verdict(self.name, "empty transcript", ("refused_short",))
