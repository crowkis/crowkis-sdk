"""FactRelevanceCheck: whether a fact the caller stated may be left out of a shared question."""

from __future__ import annotations

import re
from typing import List, Optional, Set

from ..turn import TurnFrame
from .frame_reading import CONFIDENCE_FLOOR
from .frame_words import _FUNCTION, _stem, _toks
from .word_rules import HIGH_RISK_FACT_TYPES, _high_risk

# Where a stated turn holds a second fact: "going to Goa and my husband has a heart condition".
CLAUSE_BREAK = re.compile(r"[,;.!?]|\b(?:and|but|also|plus|aur|y)\b", re.I)


class FactRelevanceCheck:
    """A stated turn ("my car was hit") may be left out of a shared question only when the model is
    sure of the turn (not abstaining, at or above the confidence floor) and tags the fact as not
    changing this answer, and only when neither the stated words nor the model's type say allergy,
    medication, pregnancy or age (the floor). Late, failed, unsure or silent: the fact counts. Each clause
    of a stated turn is a fact of its own and needs its own "does not change" entry."""

    def __init__(self, confidence_floor: float = CONFIDENCE_FLOOR) -> None:
        self._confidence_floor = confidence_floor

    def irrelevant(self, stated: str, frame: Optional[TurnFrame]) -> bool:
        """The model says, sure of it, that ``stated`` does not change the answer to this turn."""
        if frame is None or frame.abstain or frame.confidence < self._confidence_floor or _high_risk(stated):
            return False
        return all(self._clause_irrelevant(clause, frame) for clause in self._clauses(stated))

    def _clause_irrelevant(self, clause: str, frame: TurnFrame) -> bool:
        stems = self._content_stems(clause)
        about = [f for f in frame.fact_relevance if stems & self._content_stems(f.fact)]
        return bool(about) and not any(f.changes_answer or f.type in HIGH_RISK_FACT_TYPES for f in about)

    def _clauses(self, stated: str) -> List[str]:
        """The parts of a stated turn that say something (at least one content word)."""
        return [part for part in CLAUSE_BREAK.split(stated) if part and self._content_stems(part)] or [stated]

    @staticmethod
    def _content_stems(text: str) -> Set[str]:
        return {_stem(word) for word in _toks(text) if word not in _FUNCTION and len(word) > 2}
