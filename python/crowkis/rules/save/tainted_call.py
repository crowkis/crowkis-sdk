"""The TaintedCall rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict
from ...runtime.stats import Counter

KEPT = "kept"


class TaintedCall:
    """Once the caller told the call something an answer may depend on, nothing more is shared."""

    name = "TaintedCall"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.call.tainted:
            return None
        return Verdict(self.name, "kept to this call: the caller told it something the answer may depend on",
                       (Counter.NOT_SHAREABLE,), KEPT)
