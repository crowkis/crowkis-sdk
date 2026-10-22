"""The CommitmentRewording rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...understanding.word_rules import _COMMITMENTS


class CommitmentRewording:
    """A commitment (a price, a refund, a policy) is spoken only as the call's ``commitments``
    setting allows: by default, only for the exact same question."""

    name = "CommitmentRewording"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        commitments = cached.turn.call.commitments
        if not cached.hit.get("commitment") or _COMMITMENTS[commitments](cached.hit):
            return None
        reason = ("the cached answer is a commitment (a price, a refund, a policy) and "
                  f"commitments={commitments!r} does not allow speaking this match")
        return Verdict(self.name, reason, ("held_commitments", "inferred"))
