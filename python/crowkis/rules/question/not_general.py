"""The NotGeneral rule (stage 1, question; Chat, V3)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict


class NotGeneral:
    """A turn that is not a general question about no one in particular is not shared."""

    name = "NotGeneral"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if turn.frame.kind == "general" and turn.frame.subject == "none":
            return None
        return Verdict(self.name, "V3_not_general")
