"""LLMRewriter: the Rewriter slot filled by an understander's stand-alone question."""

from __future__ import annotations

from typing import Optional

from ..callstate import CallState
from ..understand import Understander
from .frame_reading import FrameReading
from .slots import Reading


class LLMRewriter:
    """Adapter: keys a shareable turn on the understander's stand-alone, de-identified question. When
    the classifier's reading already carries the model's frame (``LLMClassifier`` over the same
    understander), that frame is reused and the model is asked once per turn."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def rewrite(self, text: str, reading: Reading) -> Optional[str]:
        """The model's question for a turn that may be shared, else None (the caller's words)."""
        if reading.is_personal:
            return None
        if not isinstance(reading, FrameReading):
            reading = FrameReading(self._understander.understand(text, CallState()))
        return reading.question
