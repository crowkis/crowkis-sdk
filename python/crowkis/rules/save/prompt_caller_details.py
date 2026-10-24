"""The PromptCallerDetails rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Outcome, Verdict
from ...understanding.word_rules import _repeats_prompt_details
from ...runtime.stats import Counter


class PromptCallerDetails:
    """The model read a system prompt that names this caller, and its answer repeats that:
    right for this caller only, never a shared answer or shape."""

    name = "PromptCallerDetails"
    floor = True

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.instructions or not _repeats_prompt_details(
                answer.answer, answer.text, answer.instructions, answer.call.agent_key()):
            return None
        return Verdict(self.name, "kept to this call: the answer repeats a detail about the caller "
                                  "from the system prompt", (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)
