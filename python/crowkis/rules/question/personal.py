"""Stage 1 rules (question): about this caller (own records, identifying details, someone else, a name)."""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from ...runtime.stats import Counter
from ...state.call_state import word_digest
from ...turns.values import Verdict
from ...turns.voice.turn import VoiceTurn
from ...turns.chat.turn import ChatTurn
from ...understanding.word_rules.chat import _CALENDAR, _COMMON_ACRONYMS, _FUNCTION, _looks_identifying
from ...understanding.model.frame import NOT_GENERAL_TYPES
from ...understanding.word_rules.text import _words


OWN_RECORDS_REASON = (
    "the caller asked about their own records and this session has no "
    "values to fill a shared answer shape with, so nothing can be "
    "answered from cache without one caller's answer reaching the next"
)


class OwnRecords:
    """A question about the caller's own records ("where is my order 48213"), or another turn
    the word rules never share (urgent, identifying, unreadable), is never answered from the
    shared cache unless this call declared values to fill a shared answer shape with."""

    name = "OwnRecords"
    floor = True

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not turn.is_personal or turn.call.values:
            return None
        return Verdict(self.name, OWN_RECORDS_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


# The IdentifyingDetails rule (stage 1, question; Chat, V5).
class IdentifyingDetails:
    """An identifying entity, an email, a phone number or an ID-like digit run never enters a key."""

    name = "IdentifyingDetails"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        question = turn.question
        low = question.lower()
        if not (any(t.lower() in low for t in turn.frame.identifying_texts) or _looks_identifying(question)):
            return None
        return Verdict(self.name, "V5_identifying")


# The AboutSomeone rule (stage 1, question; Chat, V4).
class AboutSomeone:
    """An owned record, an own purchase or another person in the frame contradicts "general"."""

    name = "AboutSomeone"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not any(e.type in NOT_GENERAL_TYPES for e in turn.frame.entities):
            return None
        return Verdict(self.name, "V4_about_someone")


# The QuestionNamesCaller rule (stage 1, question; Chat, "V5_private_word", checked once the rule checker would share).
class QuestionNamesCaller:
    """The shared question says what named the caller earlier ("for sarah")."""

    name = "QuestionNamesCaller"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not any(turn.state.is_name(w) for w in _words(turn.question or "")):
            return None
        return Verdict(self.name, "V5_private_word")


# The UntaggedName rule (stage 1, question; Chat, "V5_untagged_name", checked once the rule checker would share).
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
