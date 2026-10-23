"""The LostDetail rule (stage 1, question; Chat, V7)."""

from __future__ import annotations

from typing import Optional

from ...understanding.turn_frame import DETAIL_TYPES
from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _FUNCTION, _stem, _toks


class LostDetail:
    """An answer-relevant detail of the turn (a product, a time, a place) missing from the key."""

    name = "LostDetail"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        lost = self._lost_detail(turn.frame, turn.question)
        if lost is None:
            return None
        return Verdict(self.name, "V7_lost:" + lost)

    @staticmethod
    def _lost_detail(frame, question) -> Optional[str]:
        qstems = {_stem(w) for w in _toks(question)}
        attr_text = " ".join(f"{a.value} {a.normalised}" for a in frame.attributes.values()).lower()
        for e in frame.entities:
            if e.answer_relevant and not e.identifying and e.type in DETAIL_TYPES:
                words = [w for w in _toks(e.text) if w not in _FUNCTION]
                if words and not any(_stem(w) in qstems for w in words) and not any(w in attr_text for w in words):
                    return e.text
        return None
