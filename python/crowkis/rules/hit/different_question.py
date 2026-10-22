"""The DifferentQuestion rule (stage 2, hit)."""

from __future__ import annotations

import time
from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...runtime.stats import Counter

MS_PER_SECOND = 1000.0
DIFFERENT_QUESTION_REASON = (
    "the cached answer was saved for a different question (it asks about "
    "something this one does not); a model call is better than a wrong answer"
)


class DifferentQuestion:
    """A near hit saved for a question that asks about something else is not served."""

    name = "DifferentQuestion"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        turn = cached.turn
        if turn.is_personal or cached.hit.get("exact"):
            return None
        spent_ms = (time.monotonic() - cached.started) * MS_PER_SECOND
        if not turn.call.answers_another_question(turn.key, cached.answer, spent_ms):
            return None
        return Verdict(self.name, DIFFERENT_QUESTION_REASON, (Counter.DIFFERENT_QUESTION, Counter.INFERRED))
