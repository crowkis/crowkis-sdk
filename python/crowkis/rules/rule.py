"""The rule interfaces of the three SDK check stages."""

from __future__ import annotations

from typing import Optional, Protocol

from ..turns import CachedAnswer, ModelAnswer, Verdict, VoiceTurn


class Rule(Protocol):
    """A named check. A ``floor`` rule cannot be turned off without an explicit unsafe flag."""

    name: str
    floor: bool


class QuestionRule(Rule, Protocol):
    """Stage 1: may this turn be looked up in the shared cache?"""

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        """None when the rule has no objection."""


class HitRule(Rule, Protocol):
    """Stage 2: may this cached answer be spoken for this turn?"""

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        """None when the rule has no objection."""


class SaveRule(Rule, Protocol):
    """Stage 3: may the model's answer be shared with later callers?"""

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        """None when the rule has no objection."""
