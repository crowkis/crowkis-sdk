"""The QuestionNamesCaller rule (stage 1, question; Chat, "V5_private_word", checked once the rule checker would share)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.word_rules import _words


class QuestionNamesCaller:
    """The shared question says what named the caller earlier ("for sarah")."""

    name = "QuestionNamesCaller"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not any(turn.state.is_name(w) for w in _words(turn.question or "")):
            return None
        return Verdict(self.name, "V5_private_word")
