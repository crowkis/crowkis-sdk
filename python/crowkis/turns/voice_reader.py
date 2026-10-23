"""VoiceReader: how a voice turn is understood, as TurnCore's TurnReader."""

from __future__ import annotations

from typing import Optional

from ..understanding.call_readings import CallReadings
from ..understanding.rewrite_check import RewriteCheck
from ..understanding.slots import Classifier, Rewriter
from .voice_call import VoiceCall
from .voice_turn import VoiceTurn


class VoiceReader:
    """Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite
    unless an understander is plugged in). The rewrite is kept only when ``RewriteCheck`` accepts it;
    the call's readings remember what was made of each turn. ``segment`` is where the call's answers
    are looked up (None: no segment)."""

    def __init__(self, *, classifier: Classifier, rewriter: Rewriter, rewrite_check: RewriteCheck,
                 call_readings: CallReadings, call: VoiceCall, segment: Optional[str]) -> None:
        self._classifier = classifier
        self._rewriter = rewriter
        self._rewrite_check = rewrite_check
        self._call_readings = call_readings
        self._call = call
        self._segment = segment

    def read(self, said: str) -> VoiceTurn:
        text = (said or "").strip()
        reading = self._classifier.classify(text, self._call_readings.facts)
        rewritten = self._rewrite_check.accept(text, reading, self._rewriter.rewrite(text, reading), self._call)
        self._call_readings.note(text, reading, rewritten)
        return VoiceTurn(said, self._call, reading, rewritten, segment=self._segment)
