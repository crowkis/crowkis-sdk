"""The ToolResult rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Outcome, Verdict
from ...runtime.stats import Counter


class ToolResult:
    """An answer built from a tool's result stays in the call."""

    name = "ToolResult"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.private:
            return None
        return Verdict(self.name, "kept to this call: the answer was built from a tool's result",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)
