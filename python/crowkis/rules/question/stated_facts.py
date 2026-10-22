"""The StatedFacts rule (stage 1, question; Chat, V7)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _CLAUSE_START, _FUNCTION, _GENERIC_FACT, _stem, _toks


class StatedFacts:
    """A fact the caller stated in this chat (an allergy, an age, a trip) that the question does
    not carry. Fixed code, so the allergy case never rests on the model having tagged the
    allergy: the question must keep at least one content word of each such turn. A turn with no
    readable word (another script) cannot be checked, so it keeps the question private."""

    name = "StatedFacts"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        dropped = self._dropped_statement(turn.state, turn.question)
        if dropped is None:
            return None
        return Verdict(self.name, "V7_lost:" + dropped)

    @staticmethod
    def _dropped_statement(state, question) -> Optional[str]:
        qstems = {_stem(w) for w in _toks(question)}
        for turn in state.stated:
            words = [w for w in _toks(turn) if w not in _FUNCTION and (len(w) > 2 or w.isdigit())]
            # "allergies" alone does not carry "allergic to penicillin": the specific word must be there.
            words = [w for w in words if _stem(w) not in _GENERIC_FACT] or words
            if not words or not any(_stem(w) in qstems for w in words):
                return turn
            # Every item of a list is carried: "penicillin and peanuts" is not "peanuts".
            toks = _toks(turn)
            for i, w in enumerate(toks):
                # "and I live alone" starts a new clause; it is not a list.
                if w in ("and", "or") and (i + 1 == len(toks) or toks[i + 1] not in _CLAUSE_START):
                    for side in (reversed(toks[:i]), toks[i + 1:]):
                        item = next((x for x in side if x not in _FUNCTION), None)
                        if item and (len(item) > 2 or item.isdigit()) and _stem(item) not in _GENERIC_FACT \
                                and _stem(item) not in qstems:
                            return turn
        return None
