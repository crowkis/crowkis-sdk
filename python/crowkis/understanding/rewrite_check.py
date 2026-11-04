"""accepted_rewrite: whether a rewriter's question may key a turn."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Set

from .slots import Reading
from .word_rules.identifiers import _leaks
from .word_rules.personal import _is_personal
from .word_rules.text import _numbers, _proper_nouns, _words

if TYPE_CHECKING:
    from ..turns.voice.call import SessionCall


def accepted_rewrite(text: str, reading: Reading, rewritten: object, call: "SessionCall") -> Optional[str]:
    """The rewrite to key the turn on, or None for the caller's words. A rewrite keys a turn only when that
    cannot make the call less private. The turn must be neither personal nor a follow-up, by its reading or
    the word rules (a follow-up keeps its chain as the key, so the key says what the model was shown); the
    rewrite must not read as personal, carry a declared value, or add a number or a name the caller did not
    say. Once the caller has told the call something, no rewrite is used: the classifier read those facts, and
    a rewrite could carry one into a shared key. Anything else keeps the caller's words."""
    if not isinstance(rewritten, str) or not rewritten.strip():
        return None
    if call.stated() or call.facts():
        return None
    if reading.is_personal or call.is_personal(text):
        return None
    if reading.is_context_dependent or call.is_context_dependent(text):
        return None
    if _is_personal(rewritten) or _leaks(rewritten, call.values) or _adds_details(text, rewritten):
        return None
    return rewritten.strip()


def _adds_details(text: str, rewritten: str) -> bool:
    said_numbers = set(_numbers(text))
    if any(number not in said_numbers for number in _numbers(rewritten)):
        return True
    said_words: Set[str] = {_stem(word) for word in _words(text)}
    return any(_stem(name) not in said_words for name in _proper_nouns(rewritten))


def _stem(word: str) -> str:
    """A word without case or a plural "s", so "Sunday" in a rewrite matches "sundays" said."""
    return word.lower().rstrip("s")
