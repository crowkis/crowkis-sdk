"""VoiceReader: how a voice turn is understood, as TurnCore's TurnReader."""

from __future__ import annotations

from typing import Optional

from ..state.call_state import CallState
from ..understanding.rewrite_check import RewriteCheck
from ..understanding.chat_details import _unnamed
from ..understanding.word_rules import _leans_on
from ..understanding.slots import Classifier, Rewriter
from .session_call import SessionCall
from .voice_turn import VoiceTurn

_REWRITE_CHECK = RewriteCheck()


class VoiceReader:
    """Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite
    unless an understander is plugged in). The rewrite is kept only when ``RewriteCheck`` accepts it;
    the call's state remembers what was made of each turn. ``segment`` is where the call's answers
    are looked up (None: no segment)."""

    def __init__(self, *, classifier: Classifier, rewriter: Rewriter,
                 state: CallState, call: SessionCall, segment: Optional[str]) -> None:
        self._classifier = classifier
        self._rewriter = rewriter
        self._state = state
        self._call = call
        self._segment = segment

    def read(self, said: str, turn: int) -> VoiceTurn:
        text = (said or "").strip()
        # The stated turns too, so the model can tag each as changing this answer or not (VD5).
        stated = tuple(_unnamed(told, self._state.private_raw) for told in self._state.stated)
        reading = self._classifier.classify(text, tuple(self._state.facts) + stated)
        rewritten = _REWRITE_CHECK.accept(text, reading, self._rewriter.rewrite(text, reading), self._call)
        self._state.note_reading(text, reading, rewritten)
        if _leans_on(text, (self._call.chain() or [""])[-1]):
            self._state.read_follow_up.add(text)  # keyed with the turn it leans on (T21)
        return VoiceTurn(said, self._call, reading, rewritten, segment=self._segment, number=turn)
