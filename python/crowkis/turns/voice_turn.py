"""VoiceTurn: one caller turn, as the question rules read it."""

from __future__ import annotations

from functools import cached_property
from typing import Any, Optional

from .voice_call import VoiceCall


class VoiceTurn:
    """What the caller said in one turn, the call it belongs to, and how it was understood:
    ``reading`` is the classifier's (personal, a follow-up) and ``rewritten`` the rewriter's
    stand-alone question, or None to key the turn on the caller's words."""

    def __init__(self, said: str, call: VoiceCall, reading: Any, rewritten: Optional[str] = None) -> None:
        self.said = said
        self.text = (said or "").strip()
        self.call = call
        self.reading = reading
        self.rewritten = rewritten

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
