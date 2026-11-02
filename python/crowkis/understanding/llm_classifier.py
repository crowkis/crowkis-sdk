"""LLMClassifier: the Classifier slot filled by an understander (the app's own LLM, any provider)."""

from __future__ import annotations

from typing import Sequence

from ..state.call_state import CallState
from .understanders import Understander
from .frame_reading import FrameReading


class LLMClassifier:
    """Adapter: reads a voice turn through an ``Understander`` (``LLMUnderstander`` over the app's
    ``complete`` function, or any other). The model sees the turn, the call's facts (what earlier
    frames remembered) and the turns in which the caller told it something (the same model already read
    them as they were said), so it can say which of them change this answer. The stated turns are masked (capitals, numbers,
    emails), not anonymised: plug in the app's own model, the one that already hears the call."""

    def __init__(self, understander: Understander) -> None:
        self._understander = understander

    def classify(self, text: str, facts: Sequence[str] = ()) -> FrameReading:
        """The model's reading of the turn."""
        return FrameReading(self._understander.understand(text, CallState(facts=list(facts))))
