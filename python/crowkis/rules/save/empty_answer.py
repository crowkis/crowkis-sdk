"""The EmptyAnswer rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Outcome, Verdict
from ...runtime.stats import Counter


class EmptyAnswer:
    """A model that said nothing has nothing to save."""

    name = "EmptyAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if (answer.answer or "").strip():
            return None
        return Verdict(self.name, "the model returned an empty answer", (Counter.EMPTY_ANSWERS,), Outcome.NON_ANSWER)
