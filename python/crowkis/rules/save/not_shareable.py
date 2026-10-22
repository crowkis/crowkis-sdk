"""The NotShareable rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict

KEPT = "kept"


class NotShareable:
    """An answer decide() did not let be shared (the model read more than the question) stays in the call."""

    name = "NotShareable"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.cacheable:
            return None
        return Verdict(self.name, "kept to this call: the answer depends on what this caller said",
                       ("not_shareable",), KEPT)
