"""The UncertainFrame rule (stage 1, question; Chat, V2)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict


class UncertainFrame:
    """The understanding model abstained, or is less sure than the confidence floor."""

    name = "UncertainFrame"
    floor = False

    def __init__(self, confidence_floor: float) -> None:
        self._confidence_floor = confidence_floor

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (turn.frame.abstain or turn.frame.confidence < self._confidence_floor):
            return None
        return Verdict(self.name, "V2_uncertain")
