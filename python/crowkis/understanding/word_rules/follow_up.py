"""Follow-ups and cut-offs: turns that lean on an earlier one, or stop mid-question."""

from __future__ import annotations

from typing import List

from .text import (  # noqa: F401
    _BARE,
    _CLAUSE_MARKERS,
    _FRAMING_WORDS,
    _FUNCTION_WORDS,
    _NON_REFERENTS,
    _PRONOUN_FOLLOWERS,
    _ROLES,
    _first_words,
    _has_phrase,
    _stem,
    _words,
)
from .phrases import (  # noqa: F401
    _CONNECTIVES,
    _FOLLOW_UP_WORDS,
    _MAX_TURN_CHARS,
)
from .personal import (  # noqa: F401
    _asks,
    _is_personal,
    _lookup_only,
)


_CONNECTIVE_PAIRS = frozenset({"what about", "how about", "ok and", "okay and"})


_ELLIPSIS_LEADS = frozenset(
    {"for", "with", "about", "in", "on", "at", "to", "from", "by"}
)


# Shapes that borrow their subject from the previous turn.
_FOLLOW_UP_PHRASES = (
    ("same", "for"), ("the", "same"), ("what", "else"), ("anything", "else"), ("tell", "me", "more"),
    ("which", "one"), ("instead",),
)


_FOLLOW_UP_PHRASES_BY_FIRST = _first_words(_FOLLOW_UP_PHRASES)


_FOLLOW_UP_ENDINGS = frozenset({"too", "also", "instead"})


_ANAPHOR_PHRASES = ("this one", "the second one", "the first one", "the other one")


_ANAPHORS = frozenset(
    {"that", "those", "it", "them", "they", "these", "this", "he", "she", "him", "her", "his", "hers", "their"}
)


_DEMONSTRATIVES = frozenset({"that", "those", "these", "this"})


def _has_antecedent(before: List[str]) -> bool:
    return any(word not in _FUNCTION_WORDS and word not in _NON_REFERENTS for word in before)


# "the doctor" after nothing is someone from an earlier turn, like "he".
_THE_ROLES = frozenset(
    {"doctor", "nurse", "dentist", "surgeon", "specialist", "teacher", "professor", "lawyer", "therapist"}
) | _ROLES

# A word that opens a new clause: only what came before it can be a pronoun's antecedent.
_CLAUSE_JOINERS = frozenset(
    {"and", "but", "so", "or", "then", "because", "if", "when", "while", "since", "unless", "whether",
     "that", "after", "before", "once", "although"}
)

_PERSON_PRONOUNS = frozenset({"he", "she", "him", "her", "his", "hers"})

# "fast for it": an "it" after a preposition points at an earlier topic; "return it" stays as it was.
_PREPOSITIONS = frozenset({"for", "about", "on", "with", "of", "from", "to"})


def _has_clause_antecedent(before: List[str]) -> bool:
    """Words in the question's own frame ("what days does ...") are not what a pronoun points at."""
    joiners = [i for i, word in enumerate(before) if word in _CLAUSE_JOINERS]
    return bool(joiners) and _has_antecedent(before[:joiners[-1]])


def _points_forward(words: List[str], index: int) -> bool:
    """An "it" whose subject comes after it: "what does it cost to send a parcel",
    "is it true that ...". "Is it refundable to the card" still points back."""
    for offset, word in enumerate(words[index + 1:index + 4]):
        if word in ("that", "if", "whether"):
            return True
        if word == "to":
            after = index + 2 + offset
            return after < len(words) and words[after] not in _FUNCTION_WORDS
    return False


def _has_bare_anaphor(words: List[str]) -> bool:
    joined = " ".join(words)
    for phrase in _ANAPHOR_PHRASES:
        at = joined.find(phrase)
        if at >= 0 and not _has_antecedent(joined[:at].split()):
            return True
    for index, word in enumerate(words):
        if word not in _ANAPHORS:
            continue
        follows = words[index + 1] if index + 1 < len(words) else None
        if (
            word in _DEMONSTRATIVES
            and follows is not None
            and follows not in _FUNCTION_WORDS
            and follows not in _PRONOUN_FOLLOWERS
        ):
            continue
        if word == "it" and _points_forward(words, index):
            continue
        if not _has_antecedent(words[:index]):
            return True
        if (word in _PERSON_PRONOUNS or (word == "it" and index and words[index - 1] in _PREPOSITIONS)) and not _has_clause_antecedent(words[:index]):
            return True
    for index, word in enumerate(words[1:], 1):
        if word in _THE_ROLES and words[index - 1] == "the" and not _has_clause_antecedent(words[:index - 1]):
            return True
    return False


def _is_context_dependent(text: str) -> bool:
    if len(text or "") > _MAX_TURN_CHARS:
        return False  # private anyway, and keyed on its own
    words = _words(text)
    if not words:
        return False
    if words[0] in _CONNECTIVES:
        return True
    if " ".join(words[:2]) in _CONNECTIVE_PAIRS:
        return True
    if words[0] in _ELLIPSIS_LEADS and not any(w in _CLAUSE_MARKERS for w in words[1:]):
        return True
    if _has_phrase(words, _FOLLOW_UP_PHRASES_BY_FIRST) or words[-1] in _FOLLOW_UP_ENDINGS:
        return True
    if all(w in _FUNCTION_WORDS or w in _NON_REFERENTS or w in _BARE for w in words):
        return True
    return _has_bare_anaphor(words)


def _root(word: str) -> str:
    root = _stem(word)
    return root[:-1] if len(root) > 3 and root[-1] == root[-2] else root  # "cancelling" -> "cancel"


def _leans_on(text: str, previous: str) -> bool:
    """A short question whose only topic is an "-ing" form of what the previous caller turn said
    ("How long does porting take?" after "...to port my number...") names no topic of its own: on a
    telecom call it means number porting, alone it means software. Same-form repeats ("refund" then
    "a refund") and longer questions stand alone. shortcut: -ing forms only, one earlier turn;
    upgrade with the pluggable understander."""
    words, before = _words(text), _words(previous)
    if not before or len(words) > _FOLLOW_UP_WORDS:
        return False
    roots = {_root(w) for w in before}
    shared = {_root(w) for w in words if w not in _FUNCTION_WORDS and w not in _FRAMING_WORDS
              and w not in _NON_REFERENTS and _root(w) in roots}
    return len(shared) == 1 and any(w.endswith("ing") and _root(w) in shared and w not in before for w in words)


# Words a finished question rarely ends on: "do you deliver on" was cut off before its day.
_DANGLING = frozenset(
    "on in at to for from with about of by into onto over under the a an and or but my your our their "
    "his her its than if because like as between near via per until before after during within without "
    "through since outside inside around across against any some whether".split()
)


_TRAILING_FILLERS = frozenset("um uh er erm uhm hmm mm".split())


# "How do I log in?" is finished: the verb takes the word as its own.
_TAKES_IN_ON = frozenset("log logged sign signed check checked opt opted".split())


def _unfinished(text: str) -> bool:
    words = _words(text)
    while words and words[-1] in _TRAILING_FILLERS:
        words.pop()
    if not words or words[-1] not in _DANGLING:
        return False
    return not (words[-1] in ("in", "on") and len(words) > 1 and words[-2] in _TAKES_IN_ON)


def _private_chain(chain: List[str], min_words: int = 0) -> bool:
    """A chain is private when any turn of it is, or when its root ("Priya Sharma.",
    "Bipolar.") is too short to stand alone or neither asks nor requests anything."""
    root = (chain[0] or "").strip() if chain else ""
    if chain and (len(root.split()) < min_words or not _asks(root)):
        return True
    return any(_is_personal(turn) or _lookup_only(turn) for turn in chain)
