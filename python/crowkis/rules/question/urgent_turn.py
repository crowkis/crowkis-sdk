"""The UrgentTurn rule (stage 1, question; Chat, V1)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.routes import URGENT
from ...turns.verdict import Verdict


class UrgentTurn:
    """An urgent turn (an emergency, a crisis) takes the urgent route and is never shared."""

    name = "UrgentTurn"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not turn.frame.urgent:
            return None
        return Verdict(self.name, "V1_urgent", route=URGENT)
