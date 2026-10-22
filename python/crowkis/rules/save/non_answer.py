"""The NonAnswer rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict
from ...runtime.stats import Counter

NON_ANSWER = "non_answer"


class NonAnswer:
    """An answer that asks back or does not answer is not saved."""

    name = "NonAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_non_answer:
            return None
        return Verdict(self.name, "not saved: the answer asks back or does not answer", (Counter.NOT_SHAREABLE,), NON_ANSWER)
