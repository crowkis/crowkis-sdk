"""The CallContextTaint rule (stage 1, question)."""

from __future__ import annotations

from typing import Optional

from ...turns import Verdict, VoiceTurn
from ...understanding.word_rules import _sets_context

TAINTED_REASON = (
    "the caller has told this call something a later answer may depend on "
    "(a condition, an age, a plan, an instruction, a step in their own task); "
    "a shared answer to the bare question could be wrong for them"
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
