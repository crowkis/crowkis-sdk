"""PersonalReadings: which turns of a call are personal, by the classifier's reading or the word rules."""

from __future__ import annotations

from typing import List, Set

from .slots import Reading
from .word_rules import _is_personal, _private_chain


class PersonalReadings:
    """The caller turns of one call that the classifier read as personal. A turn is personal when
    its reading or the word rules say so, so a plugged-in classifier can only make a call more
    private, never less. Kept per call: what decide() read is what record() and later follow-ups
    check."""

    def __init__(self) -> None:
        self._read_personal: Set[str] = set()

    def note(self, text: str, reading: Reading) -> None:
        """Remember a turn's reading (the stripped words the classifier read)."""
        if reading.is_personal:
            self._read_personal.add(text.strip())

    def is_personal(self, text: str) -> bool:
        """The turn is about the caller's own records, by its reading or by the word rules."""
        text = (text or "").strip()
        return text in self._read_personal or _is_personal(text)

    def chain_is_private(self, chain: List[str], min_words: int) -> bool:
        """A follow-up chain is private by the word rules, or when any turn of it was read as personal."""
        return _private_chain(chain, min_words) or any(self.is_personal(turn) for turn in chain)
