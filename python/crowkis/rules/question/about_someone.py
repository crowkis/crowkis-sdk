"""The AboutSomeone rule (stage 1, question; Chat, V4)."""

from __future__ import annotations

from typing import Optional

from ...understanding.turn_frame import NOT_GENERAL_TYPES
from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict


class AboutSomeone:
    """An owned record, an own purchase or another person in the frame contradicts "general"."""

    name = "AboutSomeone"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not any(e.type in NOT_GENERAL_TYPES for e in turn.frame.entities):
            return None
        return Verdict(self.name, "V4_about_someone")
