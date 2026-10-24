"""The PersonalTemplate rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Outcome, Verdict
from ...understanding.word_rules import _unfinished


class PersonalTemplate:
    """An answer about the caller's own records is shared only as a shape with this call's
    declared values taken out; this rule says when it cannot be (the call was told something,
    the answer does not answer, the turn was cut off, or no shape could be made)."""

    name = "PersonalTemplate"
    floor = True
    REASON = "about this caller, with no declared value to make a shared answer shape from"

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_personal:
            return None
        if answer.call.tainted or answer.is_non_answer or _unfinished(answer.text):
            return self.refusal()
        return None

    def refusal(self) -> Verdict:
        """The verdict when no shared shape is made from a personal answer."""
        return Verdict(self.name, self.REASON, (), Outcome.PRIVATE)
