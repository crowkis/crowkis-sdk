"""Stage 1 rules (question): the turn's shape (empty, short, cut off, no question, a filler, a task step, unsure)."""

from __future__ import annotations

import re
from typing import List, Mapping, Optional

from ...runtime.stats import Counter
from ...turns import Verdict, VoiceTurn
from ...turns.chat_turn import ChatTurn
from ...turns.routes import TASK
from ...understanding.frame_words import _FUNCTION, _QUESTION_WORDS, _stem, _toks
from ...understanding.word_rules import _normalise, _unfinished


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


# The NoQuestion rule (stage 1, question; Chat, V3).
class NoQuestion:
    """A frame with no stand-alone question has nothing to look up or share."""

    name = "NoQuestion"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if turn.question:
            return None
        return Verdict(self.name, "V3_no_question")


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


# The TaskStep rule (stage 1, question; Chat, V9).
# A clock time ("8:45 PM", "9 am", "21:30"): while a task runs it is one of the task's own details.
CLOCK_TIME = re.compile(r"\b\d{1,2}(:\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b|\b\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)(?!\w)", re.I)


class TaskStep:
    """A step of a task in progress (booking, ordering, a reply to the agent's own question during
    one) goes to the agent and is never shared."""

    name = "TaskStep"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (turn.frame.task_step or self._answers_agent_during_task(turn) or self._names_a_time_during_task(turn)):
            return None
        return Verdict(self.name, "V9_task_step", route=TASK)

    @staticmethod
    def _names_a_time_during_task(turn: ChatTurn) -> bool:
        """While a task runs, a question naming a clock time is about the task ("Does the 8:45 PM flight
        have a meal?" while a flight is being changed: v4, misfire C01), never a general question."""
        return turn.state.task != "none" and bool(CLOCK_TIME.search(turn.text or ""))

    @staticmethod
    def _answers_agent_during_task(turn: ChatTurn) -> bool:
        """While a task is running, a reply to the agent's own question is a step of it."""
        state = turn.state
        return state.task != "none" and state.last_reply.rstrip().endswith("?") and "?" not in (turn.text or "")


# The UncertainFrame rule (stage 1, question; Chat, V2).
class UncertainFrame:
    """The understanding model abstained, or is less sure than the confidence floor."""

    name = "UncertainFrame"
    floor = False

    def __init__(self, confidence_floor: float) -> None:
        self._confidence_floor = confidence_floor

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (turn.frame.abstain or turn.frame.confidence < self._confidence_floor):
            return None
        return Verdict(self.name, "V2_uncertain")


# The Ungrounded rule (stage 1, question; Chat, V6).
SHOWN_WORDS = 3
# A stem that starts another of at least this many letters is the same word ("visit", "visitor").
SHARED_STEM = 5


class Ungrounded:
    """A content word of the key that is not in the turn or the call state (grounding)."""

    name = "Ungrounded"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        added = self._ungrounded(turn.question, turn.text, turn.state)
        if not added:
            return None
        return Verdict(self.name, "V6_ungrounded:" + ",".join(added[:SHOWN_WORDS]))

    @staticmethod
    def _ungrounded(question, text, state) -> List[str]:
        source = set(_toks(text))
        for grounding in state.grounding_sources():
            source.update(_toks(grounding))
        stems = {_stem(w) for w in source}
        return [w for w in _toks(question) if w not in _FUNCTION and w not in source
                and not Ungrounded._grounded(_stem(w), stems) and w not in _QUESTION_WORDS]

    @staticmethod
    def _grounded(stem: str, stems) -> bool:
        """The stem, or one it starts or is started by (v4, misfire B03: "visitors" after "visiting")."""
        if stem in stems:
            return True
        return any(min(len(stem), len(other)) >= SHARED_STEM and (stem.startswith(other) or other.startswith(stem))
                   for other in stems)


# The NotGeneral rule (stage 1, question; Chat, V3).
class NotGeneral:
    """A turn that is not a general question about no one in particular is not shared."""

    name = "NotGeneral"
    floor = True

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if turn.frame.kind == "general" and turn.frame.subject == "none":
            return None
        return Verdict(self.name, "V3_not_general")
