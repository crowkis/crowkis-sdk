"""The EmptyAnswer rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict

NON_ANSWER = "non_answer"


class EmptyAnswer:
    """A model that said nothing has nothing to save."""

    name = "EmptyAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if (answer.answer or "").strip():
            return None
        return Verdict(self.name, "the model returned an empty answer", ("empty_answers",), NON_ANSWER)
