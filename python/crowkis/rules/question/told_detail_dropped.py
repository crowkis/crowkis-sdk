"""The ToldDetailDropped rule (stage 1, question; Chat, "V7_lost_detail", checked once the rule checker would share)."""

from __future__ import annotations

from typing import Optional

from ...state.call_state import word_digest
from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _NUMWORDS
from ...understanding.word_rules import _words


class ToldDetailDropped:
    """A place, month or number the caller told ("Goa in December") is missing from the question."""

    name = "ToldDetailDropped"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        words = _words(turn.question or "")
        asked = {word_digest(w) for w in words} | {word_digest(_NUMWORDS.get(w, w)) for w in words}  # "three" is "3"
        if not any(d not in asked for d in turn.state.details):
            return None
        return Verdict(self.name, "V7_lost_detail")
