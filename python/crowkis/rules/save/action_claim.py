"""The ActionClaim rule (stage 3, save; Chat, "action_claim")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.answer_patterns import _ACTION_CLAIM


class ActionClaim:
    """An answer saying something was done for this user ("I have cancelled your order") is not shared."""

    name = "ActionClaim"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not _ACTION_CLAIM.search(answer.text):
            return None
        return Verdict(self.name, "action_claim")
