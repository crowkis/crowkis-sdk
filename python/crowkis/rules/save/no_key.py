"""The NoKey rule (stage 3, save)."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict

NOT_SAVED = "not_saved"


class NoKey:
    """A follow-up with no earlier turn to key it on cannot be saved."""

    name = "NoKey"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.key is not None:
            return None
        return Verdict(self.name, "a follow-up with no earlier turn to key it on", (), NOT_SAVED)
