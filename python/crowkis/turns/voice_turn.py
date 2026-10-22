"""VoiceTurn: one caller turn, as the question rules read it."""

from __future__ import annotations

from functools import cached_property
from typing import Optional

from ..understanding.word_rules import _is_context_dependent, _is_personal
from .voice_call import VoiceCall


class VoiceTurn:
    """What the caller said in one turn, the call it belongs to, and what the word rules make
    of it. Each reading is worked out once, when a rule first needs it."""

    def __init__(self, said: str, call: VoiceCall) -> None:
        self.said = said
        self.text = (said or "").strip()
        self.call = call

    @cached_property
    def is_short(self) -> bool:
        """Too few words to match on meaning."""
        return len(self.text.split()) < self.call.min_words

    @cached_property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""
        return _is_personal(self.text)

    @cached_property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it."""
        return _is_context_dependent(self.text)

    @cached_property
    def key(self) -> Optional[str]:
        """The cache key: the caller's words, or the chain a follow-up leans on; None without one."""
        return self.call.context_key(self.said, self.text)
