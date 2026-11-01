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
        hit = cached.hit
        if not (hit.commitment or hit.unjudged) or COMMITMENT_POLICIES[commitments](hit):
            return None
        reason = ("the cached answer is a commitment (a price, a refund, a policy)" if hit.commitment
                  else "the cached answer has not been judged yet, so it may be a commitment") + (
                  f" and commitments={commitments!r} does not allow speaking this match")
        return Verdict(self.name, reason, (Counter.HELD_COMMITMENTS, Counter.INFERRED))
