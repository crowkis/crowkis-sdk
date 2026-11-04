"""WordRuleClassifier: today's word rules in the classifier slot."""

from __future__ import annotations

from functools import cached_property
from typing import Sequence

from .word_rules.follow_up import _is_context_dependent
from .word_rules.personal import _is_personal


class WordReading:
    """What the word rules make of one turn's words. Each reading is worked out once, when a
    rule first needs it."""

    # The word rules make no frame.
    frame = None

    def __init__(self, text: str) -> None:
        self.text = text

    @cached_property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""
        return _is_personal(self.text)

    @cached_property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it."""
        return _is_context_dependent(self.text)


class WordRuleClassifier:
    """The classifier a voice session uses when no understander is plugged in: the fixed word
    rules, so nothing changes without opt-in."""

    def classify(self, text: str, facts: Sequence[str] = ()) -> WordReading:
        return WordReading(text)
