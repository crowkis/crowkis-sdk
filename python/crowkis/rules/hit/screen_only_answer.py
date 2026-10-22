"""The ScreenOnlyAnswer rule (stage 2, hit)."""

from __future__ import annotations

from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...understanding.word_rules import _speakable
from ...runtime.stats import Counter

SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)"


class ScreenOnlyAnswer:
    """On a spoken channel, an answer written for a screen (a link, code or markup) is not spoken."""

    name = "ScreenOnlyAnswer"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.call.channel.spoken or _speakable(cached.answer):
            return None
        return Verdict(self.name, SCREEN_REASON, (Counter.UNSPEAKABLE, Counter.INFERRED))
