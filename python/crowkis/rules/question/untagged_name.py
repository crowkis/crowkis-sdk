"""The UntaggedName rule (stage 1, question; Chat, "V5_untagged_name", checked once the rule checker would share)."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from ...callstate import word_digest
from ...turn import NOT_GENERAL_TYPES
from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _CALENDAR, _COMMON_ACRONYMS, _FUNCTION
from ...understanding.word_rules import _words

LETTER_RUN = re.compile(r"[^\W\d_]+")
CAPITAL_OR_CASELESS = ("Lu", "Lt", "Lo")


class UntaggedName:
    """A word in the shared question with a capital ("Priya", "PRIYA", "McKenzie"), or in a script
    without capitals, that the understanding model did not tag as a place, thing or topic, that is
    no month or day, and that no earlier shared turn of this chat said. Fixed code cannot tell
    "Priya" from "France" or "SSO"; the model's tag can (it is asked to tag every one)."""

    name = "UntaggedName"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        state = turn.state
        allowed = {w for e in turn.frame.entities if not e.identifying and e.type not in NOT_GENERAL_TYPES
                   for w in _words(e.text)}
        allowed |= _CALENDAR | set(_words(state.active_question or "")) | set(_words(state.last_reply))
        flagged = set()
        for i, word in enumerate(LETTER_RUN.findall(turn.question or "")):
            low = word.lower()
            if word == "I" or (i == 0 and low in _FUNCTION):  # "What ...", "How ..."
                continue
            if word.isupper() and low in _COMMON_ACRONYMS:  # "UPI", "SIM": a thing, never "Ram" or "Sim"
                continue
            if any(unicodedata.category(c) in CAPITAL_OR_CASELESS for c in word):
                flagged.add(low)
        if not any(w not in allowed and word_digest(w) not in state.details for w in flagged):
            return None
        return Verdict(self.name, "V5_untagged_name")
