"""ModelAnswer: the model's answer to a turn, as the save rules read it."""

from __future__ import annotations

from functools import cached_property
from typing import Optional

from ..understanding.word_rules import _is_non_answer
from .session_call import SessionCall


class ModelAnswer:
    """What the model said to a turn, with what is known about that turn when it is recorded.

    ``key`` is the turn's cache key (set once the answer is known to be one), worked out before the turn joined the transcript.
    ``private`` means the answer was built from a tool's result; ``instructions`` is the system
    prompt the model read; ``cacheable`` is whether decide() let the answer be shared."""

    def __init__(self, said: str, answer: str, key: Optional[str], call: SessionCall, *, private: bool,
                 instructions: Optional[str], cacheable: bool) -> None:
        self.said = said
        self.text = (said or "").strip()
        self.answer = answer
        self.key = key
        self.call = call
        self.private = private
        self.instructions = instructions
        self.cacheable = cacheable

    @cached_property
    def is_personal(self) -> bool:
        """The turn was about the caller's own records, by its reading or by the word rules."""
        return self.call.is_personal(self.text)

    @cached_property
    def is_non_answer(self) -> bool:
        """The answer asks back or does not answer."""
        return _is_non_answer(self.answer)
