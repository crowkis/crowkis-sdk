"""The CallerIdentifier rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict
from ...understanding.word_rules import _repeats_identifier

PRIVATE = "private"


class CallerIdentifier:
    """An answer repeating a number or ID this caller said is never shared. Its model read only
    the question, so this can only come from an app that sent it the whole call."""

    name = "CallerIdentifier"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _repeats_identifier(answer.answer, answer.call.said_identifiers()):
            return None
        return Verdict(self.name, "kept to this call: the answer repeats a number or ID this caller said",
                       ("not_shareable",), PRIVATE)
