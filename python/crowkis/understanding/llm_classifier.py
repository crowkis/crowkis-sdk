"""LLMClassifier: the Classifier slot filled by an understander (the app's own LLM, any provider)."""

from __future__ import annotations

from typing import Sequence

from ..callstate import CallState
from ..understand import Understander
from .frame_reading import FrameReading


class LLMClassifier:
    """Adapter: reads a voice turn through an ``Understander`` (``LLMUnderstander`` over the app's
    ``complete`` function, or any other). The model sees the turn and the call's de-identified facts
    (what earlier frames remembered, never a name, a number or an earlier turn), so it can say which
    facts change this answer."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def classify(self, text: str, facts: Sequence[str] = ()) -> FrameReading:
        """The model's reading of the turn."""
        return FrameReading(self._understander.understand(text, CallState(facts=list(facts))))
