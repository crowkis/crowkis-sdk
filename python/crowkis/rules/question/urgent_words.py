"""The UrgentWords rule (stage 1, question; Chat, "V1_urgent_fixed", checked once the rule checker would share)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.routes import URGENT
from ...turns.verdict import Verdict
from ...understanding.word_rules import _tells_about_caller, _urgent, _words


class UrgentWords:
    """A turn about the caller that the fixed urgent words catch takes the urgent route, whatever
    the model said: an emergency is never left to the model alone."""

    name = "UrgentWords"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (_tells_about_caller(turn.text) and _urgent(_words(turn.text))):
            return None
        return Verdict(self.name, "V1_urgent_fixed", route=URGENT)
