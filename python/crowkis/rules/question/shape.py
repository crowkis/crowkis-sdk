"""Stage 1 rules (question): the turn's shape (empty, short, cut off, a filler)."""

from __future__ import annotations

from typing import Mapping, Optional

from ...runtime.stats import Counter
from ...turns.values import Verdict
from ...turns.voice.turn import VoiceTurn
from ...understanding.word_rules.follow_up import _unfinished
from ...understanding.word_rules.text import _normalise


class EmptyTurn:
    """An empty transcript goes to the model."""

    name = "EmptyTurn"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if turn.text:
            return None
        return Verdict(self.name, "empty transcript", (Counter.REFUSED_SHORT,))


class TooShort:
    """A turn too short to match on meaning ("thank you") is not looked up, unless short
    turns are on and the server's decision engine vouches for what it caches."""

    name = "TooShort"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not turn.is_short or (turn.call.short_turns and turn.call.engine_vouches()):
            return None
        return Verdict(self.name, "transcript too short to match safely", (Counter.REFUSED_SHORT,))


class CutOff:
    """A cut-off question ("do you deliver on") is close in meaning to a full one but asks
    something else: never served a stored answer, never stored."""

    name = "CutOff"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not _unfinished(turn.text):
            return None
        return Verdict(self.name, "the turn was cut off mid-question", (Counter.REFUSED_SHORT,))


# The RegisteredFiller rule (stage 1, question; operational).
FILLER_ROUTE = "filler"
FILLER_REASON = "registered filler, answered without a lookup or a model"


class RegisteredFiller:
    """A turn the app registered a filler for ("hello") is answered with it at once: no lookup and
    no model. ``fillers`` is the session's own map (normalised trigger to reply), read live, so
    fillers registered later count."""

    name = "RegisteredFiller"
    floor = False

    def __init__(self, fillers: Mapping[str, str]) -> None:
        self._fillers = fillers

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        filler = self._fillers.get(_normalise(turn.text))
        if filler is None:
            return None
        return Verdict(self.name, FILLER_REASON, (Counter.FILLED,), route=FILLER_ROUTE, answer=filler)


# A clock time ("8:45 PM", "9 am", "21:30"): while a task runs it is one of the task's own details.
# A stem that starts another of at least this many letters is the same word ("visit", "visitor").
