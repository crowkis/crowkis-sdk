"""Question rules about what the caller told this call."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...understanding.word_rules import _private_chain, _sets_context

TAINTED_REASON = (
    "the caller has told this call something a later answer may depend on "
    "(a condition, an age, a plan, an instruction, a step in their own task); "
    "a shared answer to the bare question could be wrong for them"
)
PRIVATE_CHAIN_REASON = (
    "a follow-up to a private turn of this call: its answer depends on "
    "what this caller said, so it is never answered from a shared cache"
)


class CallContextTaint:
    """Once the caller tells the call something a later answer may depend on (a condition, an
    age, a plan, an instruction), every later turn of the call is private. The voice default
    until an understander can tell which stated facts change an answer."""

    name = "CallContextTaint"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not (turn.call.tainted or _sets_context(turn.text)):
            return None
        turn.call.mark_tainted()
        return Verdict(self.name, TAINTED_REASON, ("refused_private", "inferred"))


class PrivateChain:
    """A follow-up to a private turn of the call, or any turn after an urgent one, is private:
    its answer depends on what this caller said."""

    name = "PrivateChain"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        follows_private = turn.is_context_dependent and _private_chain(turn.call.chain() or [], turn.call.min_words)
        if not (follows_private or turn.call.after_urgent(turn.text)):
            return None
        return Verdict(self.name, PRIVATE_CHAIN_REASON, ("refused_private", "inferred"))
