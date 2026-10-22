"""The NoQuestion rule (stage 1, question; Chat, V3)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict


class NoQuestion:
    """A frame with no stand-alone question has nothing to look up or share."""

    name = "NoQuestion"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if turn.question:
            return None
        return Verdict(self.name, "V3_no_question")
