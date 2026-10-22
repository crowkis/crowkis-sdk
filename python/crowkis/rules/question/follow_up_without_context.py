"""The FollowUpWithoutContext rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...runtime.stats import Counter

NO_KEY_REASON = (
    "the utterance only has meaning against an earlier turn and this "
    "call has none, so no cache key can be built for it"
)


class FollowUpWithoutContext:
    """A follow-up ("and what about that") with no earlier turn to lean on has no cache key."""

    name = "FollowUpWithoutContext"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if turn.key is not None:
            return None
        return Verdict(self.name, NO_KEY_REASON, (Counter.INFERRED,))
