"""The TemplateSlotMissing rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...runtime.stats import Counter

SLOT_MISSING_REASON = (
    "the shared answer shape has a slot this call has no value "
    "for; speaking a half-filled answer is worse than a model call"
)


class TemplateSlotMissing:
    """A shared answer shape with a slot this call has no value for is never half spoken."""

    name = "TemplateSlotMissing"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_personal or cached.answer is not None:
            return None
        return Verdict(self.name, SLOT_MISSING_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
