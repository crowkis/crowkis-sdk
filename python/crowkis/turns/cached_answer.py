"""CachedAnswer: a hit, as the hit rules read it."""

from __future__ import annotations

from functools import cached_property
from typing import Any, Optional

from ..understanding.word_rules import _fill
from .hit import Hit


class CachedAnswer:
    """What the cache returned for a turn: a voice ``VoiceTurn``, or the shared question a chat
    looked up (``ChatHitTurn``, never personal). ``started`` is when the lookup began
    (``time.monotonic()``)."""

    def __init__(self, turn: Any, hit: Hit, started: float) -> None:
        self.turn = turn
        self.hit = hit
        self.started = started

    @cached_property
    def answer(self) -> Optional[str]:
        """The text to speak: for a personal turn, the shared answer shape filled with this
        call's values, or None when a slot has no value. Read only for a confident hit."""
        if self.turn.is_personal:
            return _fill(self.hit.answer, self.turn.call.values)
        return self.hit.answer
