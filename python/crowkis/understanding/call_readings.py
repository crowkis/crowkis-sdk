"""CallReadings: how the turns of one call were understood, for the steps that come after decide()."""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .slots import Reading
from .word_rules import _is_personal, _private_chain


class CallReadings:
    """What the classifier and rewriter made of each caller turn of one call, kept so that record()
    and later follow-ups read the turn the way decide() did.

    A turn is personal when its reading or the word rules say so, so a plugged-in classifier can only
    make a call more private, never less. A rewritten turn's answer is saved under the question it was
    looked up with."""

    def __init__(self) -> None:
        self._read_personal: Set[str] = set()
        self._rewritten: Dict[str, str] = {}

    def note(self, text: str, reading: Reading, rewritten: Optional[str]) -> None:
        """Remember a turn's reading and rewrite (keyed by the stripped words the classifier read)."""
        text = text.strip()
        if reading.is_personal:
            self._read_personal.add(text)
        if rewritten is not None:
            self._rewritten[text] = rewritten

    def is_personal(self, text: str) -> bool:
        """The turn is about the caller's own records, by its reading or by the word rules."""
        text = (text or "").strip()
        return text in self._read_personal or _is_personal(text)

    def chain_is_private(self, chain: List[str], min_words: int) -> bool:
        """A follow-up chain is private by the word rules, or when any turn of it was read as personal."""
        return _private_chain(chain, min_words) or any(self.is_personal(turn) for turn in chain)

    def rewritten(self, text: str) -> Optional[str]:
        """The stand-alone question this turn was looked up with, or None when it was not rewritten."""
        return self._rewritten.get((text or "").strip())
