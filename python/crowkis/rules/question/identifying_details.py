"""The IdentifyingDetails rule (stage 1, question; Chat, V5)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _looks_identifying


class IdentifyingDetails:
    """An identifying entity, an email, a phone number or an ID-like digit run never enters a key."""

    name = "IdentifyingDetails"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        question = turn.question
        low = question.lower()
        if not (any(t.lower() in low for t in turn.frame.identifying_texts) or _looks_identifying(question)):
            return None
        return Verdict(self.name, "V5_identifying")
