"""The UnresolvedReference rule (stage 1, question; Chat, V10)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _CONTRACTION, _FUNCTION, _QUESTION_WORDS, _REFERRING, _toks


class UnresolvedReference:
    """The model says the turn leans on the chat ("how far is it from London?") but the turn or its
    question says "it" and the question names nothing new from the chat (a neutral "population"
    names nothing; "Who is their president?" -> "Who is the president?" dropped it): the reference
    was not resolved. A rewrite that resolved it ("Is it safe to eat pad thai in Thailand?") keeps
    a filler "it" and is fine."""

    name = "UnresolvedReference"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        qwords, said = set(_toks(turn.question)), set(_toks(turn.text))
        named = {w for w in qwords - said if w not in _FUNCTION and w not in _QUESTION_WORDS and w not in _CONTRACTION}
        if not (turn.frame.uses_state and (qwords | said) & _REFERRING and not named):
            return None
        return Verdict(self.name, "V10_unresolved")
