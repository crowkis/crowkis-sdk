"""The ConfidenceBar rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...runtime.stats import Counter

CACHE_ROUTE = "cache"


class ConfidenceBar:
    """A hit below the spoken-answer bar (or a miss) goes to the model."""

    name = "ConfidenceBar"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if cached.hit["route"] == CACHE_ROUTE:
            return None
        reason = f"confidence below the spoken-answer bar of {cached.turn.call.serve_above}"
        return Verdict(self.name, reason, (Counter.INFERRED,))
