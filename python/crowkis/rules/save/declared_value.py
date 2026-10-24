"""The DeclaredValue rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Outcome, Verdict
from ...understanding.word_rules import _leaks
from ...runtime.stats import Counter


class DeclaredValue:
    """An answer holding a value declared for this call is never shared."""

    name = "DeclaredValue"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _leaks(answer.answer, answer.call.values):
            return None
        return Verdict(self.name, "kept to this call: the answer contains a value declared for this call",
                       (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)
