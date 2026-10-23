"""The StatedFacts rule for voice with an understander (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns import Verdict, VoiceTurn
from ...understanding.fact_relevance import FactRelevanceCheck
from ...understanding.word_rules import _sets_context

TELLS_REASON = "the turn tells the call something a later answer may depend on; its own answer stays with this caller"
DEPENDS_REASON = (
    "the caller told this call something that may change this answer (or the model could not say it does "
    "not); a shared answer to the bare question could be wrong for them"
)


class VoiceStatedFacts:
    """Replaces CallContextTaint when an understander is plugged in: a turn that tells the call
    something (a condition, an age, a plan) stays private, and so does each later turn unless the
    model is sure that none of the stated facts changes its answer and none is an allergy, a
    medication, a pregnancy or an age. Unsure, late or failed: private, as before. Instead of
    tainting the call, it keeps just that turn private (``mark_private``)."""

    name = "VoiceStatedFacts"
    floor = False

    def __init__(self, relevance: Optional[FactRelevanceCheck] = None) -> None:
        self._relevance = relevance if relevance is not None else FactRelevanceCheck()

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if _sets_context(turn.text):
            return self._private(turn, TELLS_REASON)
        if any(not self._relevance.irrelevant(stated, turn.frame) for stated in turn.call.stated()):
            return self._private(turn, DEPENDS_REASON)
        return None

    def _private(self, turn: VoiceTurn, reason: str) -> Verdict:
        turn.call.mark_private(turn.text)
        return Verdict(self.name, reason, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
