"""Stage 1 rules (question): an urgent turn."""

from __future__ import annotations

from typing import Optional

from ...turns.chat.turn import ChatTurn
from ...turns.results import URGENT
from ...turns.values import Verdict
from ...understanding.word_rules.call_context import _tells_about_caller
from ...understanding.word_rules.text import _words
from ...understanding.word_rules.urgent import _urgent


# The UrgentTurn rule (stage 1, question; Chat, V1).
class UrgentTurn:
    """An urgent turn (an emergency, a crisis) takes the urgent route and is never shared."""

    name = "UrgentTurn"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not turn.frame.urgent:
            return None
        return Verdict(self.name, "V1_urgent", route=URGENT)


# The UrgentWords rule (stage 1, question; Chat, "V1_urgent_fixed", checked once the rule checker would share).
class UrgentWords:
    """A turn about the caller that the fixed urgent words catch takes the urgent route, whatever
    the model said: an emergency is never left to the model alone."""

    name = "UrgentWords"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (_tells_about_caller(turn.text) and _urgent(_words(turn.text))):
            return None
        return Verdict(self.name, "V1_urgent_fixed", route=URGENT)
