"""The Ungrounded rule (stage 1, question; Chat, V6)."""

from __future__ import annotations

from typing import Optional

from typing import List

from ...turns.chat_turn import ChatTurn
from ...turns.verdict import Verdict
from ...understanding.frame_words import _FUNCTION, _QUESTION_WORDS, _stem, _toks

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
