"""The PrivateChain rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...understanding.word_rules import _private_chain
from ...runtime.stats import Counter

PRIVATE_CHAIN_REASON = (
    "a follow-up to a private turn of this call: its answer depends on "
    "what this caller said, so it is never answered from a shared cache"
)


class PrivateChain:
    """A follow-up to a private turn of the call, or any turn after an urgent one, is private:
    its answer depends on what this caller said."""

    name = "PrivateChain"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        follows_private = turn.is_context_dependent and _private_chain(turn.call.chain() or [], turn.call.min_words)
        if not (follows_private or turn.call.after_urgent(turn.text)):
            return None
        return Verdict(self.name, PRIVATE_CHAIN_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
