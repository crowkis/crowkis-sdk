"""Identifiers and declared values: whether an answer repeats a caller's ID, value or call context."""

from __future__ import annotations

import re
from typing import Dict, Iterable, List

from .text import (  # noqa: F401
    _FUNCTION_WORDS,
    _first_words,
    _flatten,
    _has_phrase,
    _proper_nouns,
    _words,
)
from .phrases import (  # noqa: F401
    _SPACED_DIGITS,
    _STEERING,
)


def _leaks(shaped: str, values: Dict[str, str]) -> bool:
    flat = _flatten(shaped)
    return any(value and _flatten(value) in flat for value in values.values())


# A token that can identify someone: an order number, a PAN or IBAN, an email, an IP address.
_ID_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._@+-]*[A-Za-z0-9]")


_YEAR = re.compile(r"(?:19|20)[0-9]{2}")


def _identifiers(texts: Iterable[str]) -> set:
    """The ID-like values said in ``texts``, flattened as _leaks compares them: tokens
    with four or more digits (not a bare year) or an @, and digit groups said with
    spaces ("2345 6789 0123")."""
    found: set = set()
    for text in texts:
        for token in _ID_TOKEN.findall(text or ""):
            digits = sum(c in "0123456789" for c in token)
            if "@" in token or (digits >= 4 and not _YEAR.fullmatch(token)):
                found.add(_flatten(token))
        for group in _SPACED_DIGITS.findall(text or ""):
            joined = "".join(c for c in group if c in "0123456789")
            if len(joined) >= 5:
                found.add(joined)
    return {value for value in found if len(value) >= 4}


def _repeats_identifier(answer: str, identifiers: set) -> bool:
    """Whether ``answer`` says one of ``identifiers``. A short value must be a whole token
    of the answer ("1800" is not in "21,800"); a long one may appear anywhere in it."""
    flat = _flatten(answer)
    tokens = {_flatten(token) for token in _ID_TOKEN.findall(answer or "")} | set(_words(answer))
    return any(value in flat if len(value) >= 6 else value in tokens for value in identifiers)


_STEERING_BY_FIRST = _first_words(_STEERING)


# Phrases after which the caller gives a name: "my name is sarah", "this is raj".
_NAMING = (("name", "is"), ("call", "me"), ("this", "is"), ("i", "m"), ("i", "am"))


def _identifying(turn: str) -> set:
    """What in a caller turn identifies the caller rather than the topic:
    numbers, names they gave, proper nouns — or, for a turn steering the model,
    every content word, since any of them can reshape the answer."""
    words = _words(turn)
    if _has_phrase(words, _STEERING_BY_FIRST):
        return {w for w in words if len(w) >= 3} - _FUNCTION_WORDS
    found = {w for w in words if any(c.isdigit() for c in w)} | _proper_nouns(turn)
    for index in range(len(words)):
        for phrase in _NAMING:
            end = index + len(phrase)
            if tuple(words[index:end]) == phrase and end < len(words) and words[end] not in _FUNCTION_WORDS:
                found.add(words[end])
    return found


def _carries_call_context(answer: str, question: str, earlier: List[str]) -> bool:
    """Whether the answer repeats something identifying the caller said earlier.

    A model answering turn N has seen turns 1..N-1, so "Sarah, order 55512
    arrives Tuesday" to "what is the delivery time?" — or an answer shaped by
    "pretend refunds are unlimited" — would be cached as the shared answer to
    a generic question and spoken to the next caller. Only identifying words
    count: "order" said earlier must not block "the order ships in 5 days".
    """
    asked = set(_words(question))
    before = set().union(*(_identifying(turn) for turn in earlier)) if earlier else set()
    return any(w in before and w not in asked for w in _words(answer))
