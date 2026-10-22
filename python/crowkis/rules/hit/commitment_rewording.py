"""The CommitmentRewording rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from .commitment_policy import COMMITMENT_POLICIES
from ...runtime.stats import Counter


class CommitmentRewording:
    """A commitment (a price, a refund, a policy) is spoken only as the call's ``commitments``
    setting allows: by default, only for the exact same question."""

    name = "CommitmentRewording"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        commitments = cached.turn.call.commitments
        if not cached.hit.commitment or COMMITMENT_POLICIES[commitments](cached.hit):
            return None
        reason = ("the cached answer is a commitment (a price, a refund, a policy) and "
                  f"commitments={commitments!r} does not allow speaking this match")
        return Verdict(self.name, reason, (Counter.HELD_COMMITMENTS, Counter.INFERRED))
