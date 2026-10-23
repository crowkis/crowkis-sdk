"""FrameReading: a Reading built from an understander's TurnFrame."""

from __future__ import annotations

from .turn_frame import TurnFrame

# The frame kinds a voice call may share: the same answer for every caller.
SHAREABLE_KIND = "general"
# A turn that only means something next to the turn before it.
FOLLOW_UP_KIND = "dialogue"
# Below this the frame is a guess, and a guess is read as private (Chat's rule checker uses the same floor).
CONFIDENCE_FLOOR = 0.6


class FrameReading:
    """What a model made of a turn, as the voice rules read it. Anything but a confident, general turn
    about no one in particular reads as personal: a weak or unsure model costs cache hits, never
    privacy. ``frame`` is kept so the rewriter reuses it instead of asking the model again."""

    def __init__(self, frame: TurnFrame) -> None:
        self.frame = frame

    @property
    def is_personal(self) -> bool:
        """Not a confident, general question: never shared."""
        frame = self.frame
        return (frame.kind != SHAREABLE_KIND or frame.abstain or frame.urgent or frame.subject != "none"
                or frame.confidence < CONFIDENCE_FLOOR or bool(frame.identifying_texts))

    @property
    def is_context_dependent(self) -> bool:
        """The model needed the call so far to read it."""
        return self.frame.uses_state or self.frame.kind == FOLLOW_UP_KIND

    @property
    def question(self) -> "str | None":
        """The stand-alone question to look the turn up with, only for a turn that may be shared."""
        return None if self.is_personal else self.frame.question
