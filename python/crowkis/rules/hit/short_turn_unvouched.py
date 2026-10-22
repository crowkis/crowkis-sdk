"""The ShortTurnUnvouched rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...runtime.stats import Counter

SHORT_TURN_REASON = (
    "a short turn is only answered from cache once the answer has been "
    "judged to stand on its own, and this one has not"
)


class ShortTurnUnvouched:
    """A short turn is served only an exact match the server's decision engine has vouched for."""

    name = "ShortTurnUnvouched"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_short or (cached.hit.vouched and cached.hit.exact):
            return None
        return Verdict(self.name, SHORT_TURN_REASON, (Counter.INFERRED,))
