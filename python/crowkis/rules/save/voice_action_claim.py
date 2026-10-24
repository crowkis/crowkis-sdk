"""The VoiceActionClaim rule (stage 3, save; voice with an understander)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns import ModelAnswer, Outcome, Verdict
from ...understanding.answer_patterns import _ACTION_CLAIM


class VoiceActionClaim:
    """Chat's ActionClaim on voice (v4): an answer saying something was done for this caller ("I have
    cancelled your order") is not shared."""

    name = "VoiceActionClaim"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _ACTION_CLAIM.search(answer.answer or ""):
            return None
        return Verdict(self.name, "kept to this call: the answer says something was done for this caller",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)
