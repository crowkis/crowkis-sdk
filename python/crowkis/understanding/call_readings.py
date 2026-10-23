"""CallReadings: how the turns of one call were understood, for the steps that come after decide()."""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Set

from .chat_details import _private_words
from .slots import Reading
from .word_rules import _is_context_dependent, _is_personal, _private_chain, _sets_context

# The newest facts and stated turns a call keeps (as Chat's CallState does).
MAX_FACTS = 12
MAX_STATED = 12


class CallReadings:
    """What the classifier and rewriter made of each caller turn of one call, kept so that record()
    and later follow-ups read the turn the way decide() did.

    A turn is personal, or a follow-up, when its reading or the word rules say so, so a plugged-in
    classifier can only make a call more private, never less. A rewritten turn's answer is saved under
    the question it was looked up with; each turn sets or clears its rewrite, so an earlier turn's never
    keys a later one. It also keeps what the caller told the call: the stated turns (never sent
    anywhere; StatedFacts checks them) and the de-identified facts the model's frames remembered
    (the classifier reads them)."""

    def __init__(self) -> None:
        self._read_personal: Set[str] = set()
        self._read_follow_up: Set[str] = set()
        self._rewritten: Dict[str, str] = {}
        self._stated: List[str] = []
        self._facts: List[str] = []
        self._private_words: Set[str] = set()

    def note(self, text: str, reading: Reading, rewritten: Optional[str]) -> None:
        """Remember a turn's reading and rewrite (keyed by the stripped words the classifier read)."""
        text = text.strip()
        if reading.is_personal:
            self._read_personal.add(text)
        if self.is_personal(text):
            self._private_words.update(_private_words(text, getattr(reading, "frame", None)))
        if reading.is_context_dependent:
            self._read_follow_up.add(text)
        if rewritten is None:
            self._rewritten.pop(text, None)
        else:
            self._rewritten[text] = rewritten
        if _sets_context(text):
            self._stated = (self._stated + [text])[-MAX_STATED:]
        frame = getattr(reading, "frame", None)
        if frame is not None:
            for entity in frame.memorable:
                fact = f"{entity.type}: {entity.text}"
                self._facts = ([f for f in self._facts if f != fact] + [fact])[-MAX_FACTS:]

    def mark_private(self, text: str) -> None:
        """Read this turn as personal from now on (a rule kept it private)."""
        self._read_personal.add((text or "").strip())
        self._private_words.update(_private_words(text or ""))

    def private_words(self) -> Set[str]:
        """Every word that may identify the caller in the turns kept private (names, numbers, capitalised
        words), lower case. Never sent anywhere."""
        return set(self._private_words)

    @property
    def stated(self) -> Sequence[str]:
        """The turns in which the caller told the call something, oldest first."""
        return tuple(self._stated)

    @property
    def facts(self) -> Sequence[str]:
        """The call's de-identified facts ("condition: car hit"), as the classifier reads them."""
        return tuple(self._facts)

    def is_personal(self, text: str) -> bool:
        """The turn is about the caller's own records, by its reading or by the word rules."""
        text = (text or "").strip()
        return text in self._read_personal or _is_personal(text)

    def is_context_dependent(self, text: str) -> bool:
        """The turn only means something next to the one before, by its reading or by the word rules."""
        text = (text or "").strip()
        return text in self._read_follow_up or _is_context_dependent(text)

    def chain_is_private(self, chain: List[str], min_words: int) -> bool:
        """A follow-up chain is private by the word rules, or when any turn of it was read as personal."""
        return _private_chain(chain, min_words) or any(self.is_personal(turn) for turn in chain)

    def rewritten(self, text: str) -> Optional[str]:
        """The stand-alone question this turn was looked up with, or None when it was not rewritten."""
        return self._rewritten.get((text or "").strip())
