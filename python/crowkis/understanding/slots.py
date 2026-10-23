"""The understanding slots: what a classifier and a rewriter give a turn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Protocol, Sequence

if TYPE_CHECKING:
    from ..turn import TurnFrame


class Reading(Protocol):
    """What a classifier makes of one turn's words."""

    @property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""

    @property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it."""

    @property
    def frame(self) -> "Optional[TurnFrame]":
        """The model's frame of the turn, or None for a reading without one (the word rules)."""


class Classifier(Protocol):
    """Reads a turn (WordRuleClassifier today; an LLM or ONNX model later). ``facts`` are the
    call's de-identified stated facts ("condition: car hit"), never its earlier turns."""

    def classify(self, text: str, facts: Sequence[str] = ()) -> Reading:
        """What this turn is."""


class Rewriter(Protocol):
    """Turns a follow-up into a stand-alone question (NoRewrite today)."""

    def rewrite(self, text: str, reading: Reading) -> Optional[str]:
        """The stand-alone question, or None to key the turn on the caller's words."""
