"""A voice turn as read (VoiceTurn, VoiceReader) and the model's answer to it (ModelAnswer)."""

from __future__ import annotations

from functools import cached_property
from typing import Any, Dict, Optional

from ...state.call_state import CallState
from ...understanding.word_rules.chat import _unnamed
from ...understanding.model.checks import accepted_rewrite
from ...understanding.slots import Classifier, Rewriter
from ...understanding.word_rules.answers import _is_non_answer
from ...understanding.word_rules.follow_up import _leans_on
from ...understanding.word_rules.text import _CONTEXT_BOUND_THRESHOLD
from .call import SessionCall

class VoiceTurn:
    """What the caller said in one turn, the call it belongs to, and how it was understood:
    ``reading`` is the classifier's (personal, a follow-up) and ``rewritten`` the rewriter's
    stand-alone question, or None to key the turn on the caller's words. ``segment`` is where the
    call's answers are looked up (None: no segment, as before); ``number`` is the turn's number in
    the call."""

    def __init__(self, said: str, call: SessionCall, reading: Any, rewritten: Optional[str] = None, *,
                 segment: Optional[str] = None, number: int = 0) -> None:
        self.said = said
        self.text = (said or "").strip()
        self.call = call
        self.reading = reading
        self.rewritten = rewritten
        self.segment = segment
        self.number = number

    @cached_property
    def is_short(self) -> bool:
        """Too few words to match on meaning."""
        return len(self.text.split()) < self.call.min_words

    @property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""
        return self.reading.is_personal or self.call.is_personal(self.text)

    @property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it, by its reading or the word rules."""
        return self.reading.is_context_dependent or self.call.is_context_dependent(self.text)

    @property
    def frame(self):
        """The model's frame of the turn, or None (the word rules make none)."""
        return getattr(self.reading, "frame", None)

    @cached_property
    def key(self) -> Optional[str]:
        """The cache key: the rewritten question, else the caller's words or the chain a
        follow-up leans on; None without one."""
        if self.rewritten is not None:
            return self.rewritten
        return self.call.context_key(self.said, self.text)

    @property
    def lookup_options(self) -> Dict[str, Any]:
        """What the lookup sends besides the key: a template lookup for a personal turn, the stricter
        threshold for a follow-up or a short turn, and the segment only when there is one (with an
        understander, kb=<version>): the default lookup is as it was."""
        options: Dict[str, Any] = {
            "template": self.is_personal,
            "threshold": _CONTEXT_BOUND_THRESHOLD if self.is_context_dependent or self.is_short else None,
        }
        if self.segment:
            options["segment"] = self.segment
        return options


class ModelAnswer:
    """What the model said to a turn, with what is known about that turn when it is recorded.

    ``key`` is the turn's cache key (set once the answer is known to be one), worked out before the turn joined the transcript.
    ``private`` means the answer was built from a tool's result; ``instructions`` is the system
    prompt the model read; ``cacheable`` is whether decide() let the answer be shared."""

    def __init__(self, said: str, answer: str, key: Optional[str], call: SessionCall, *, private: bool,
                 instructions: Optional[str], cacheable: bool) -> None:
        self.said = said
        self.text = (said or "").strip()
        self.answer = answer
        self.key = key
        self.call = call
        self.private = private
        self.instructions = instructions
        self.cacheable = cacheable

    @cached_property
    def is_personal(self) -> bool:
        """The turn was about the caller's own records, by its reading or by the word rules."""
        return self.call.is_personal(self.text)

    @cached_property
    def is_non_answer(self) -> bool:
        """The answer asks back or does not answer."""
        return _is_non_answer(self.answer)


class VoiceReader:
    """Reads a caller's turn with the classifier and the rewriter (the word rules and no rewrite
    unless an understander is plugged in). The rewrite is kept only when ``accepted_rewrite`` accepts it;
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
        rewritten = accepted_rewrite(text, reading, self._rewriter.rewrite(text, reading), self._call)
        self._state.note_reading(text, reading, rewritten)
        if _leans_on(text, (self._call.chain() or [""])[-1]):
            self._state.read_follow_up.add(text)  # keyed with the turn it leans on (T21)
        return VoiceTurn(said, self._call, reading, rewritten, segment=self._segment, number=turn)
