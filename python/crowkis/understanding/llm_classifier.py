"""LLMClassifier: the Classifier slot filled by an understander (the app's own LLM, any provider)."""

from __future__ import annotations

from ..callstate import CallState
from ..understand import Understander
from .frame_reading import FrameReading


class LLMClassifier:
    """Adapter: reads a voice turn through an ``Understander`` (``LLMUnderstander`` over the app's
    ``complete`` function, or any other). The model sees the turn alone, never the caller's earlier
    words, so nothing else the caller said crosses to the provider."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def classify(self, text: str) -> FrameReading:
        """The model's reading of the turn."""
        return FrameReading(self._understander.understand(text, CallState()))
