"""ReplayRewriter: the Rewriter slot for exact repeats of already-verified questions."""

from __future__ import annotations

from typing import Dict, Optional

from ..state.call_state import CallState
from .understanders import ReplayUnderstander
from .frame_reading import FrameReading
from .slots import Reading


class ReplayRewriter:
    """Keys a turn on a verified question only when the turn repeats it word for word (case,
    punctuation and spacing aside); anything else keeps the caller's words. It needs no model and
    cannot be talked into a different question."""

    def __init__(self, known: Optional[Dict[str, str]] = None) -> None:
        self._replay = ReplayUnderstander(known)

    def remember(self, turn: str, question: str, question_type: str = "other") -> None:
        """Recognise ``turn`` (and ``question`` itself) as the verified ``question`` from now on."""
        self._replay.remember(turn, question, question_type)

    def rewrite(self, text: str, reading: Reading) -> Optional[str]:
        """The verified question this turn repeats, or None (also for a turn read as personal)."""
        if reading.is_personal:
            return None
        return FrameReading(self._replay.understand(text, CallState())).question
