"""The PiiPlaceholder rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...understanding.word_rules import _PII_PLACEHOLDER

PLACEHOLDER_REASON = (
    "the cached answer holds a placeholder the server put in place of a "
    "caller's detail; reading it aloud is worse than a model call"
)


class PiiPlaceholder:
    """An answer holding a placeholder the server put in place of a caller's detail is never read aloud."""

    name = "PiiPlaceholder"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not _PII_PLACEHOLDER.search(cached.answer):
            return None
        return Verdict(self.name, PLACEHOLDER_REASON, ("refused_private", "inferred"))
