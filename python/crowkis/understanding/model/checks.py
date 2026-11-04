"""What may come of a model's output: whether a rewrite may key a turn, and whether a stated fact may
be left out of a shared question."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, List, Optional, Set

from ..slots import Reading
from ..word_rules.call_context import HIGH_RISK_FACT_TYPES, _high_risk
from ..word_rules.chat import _FUNCTION, _stem, _toks
from ..word_rules.personal import _leaks, _is_personal
from ..word_rules.text import _numbers, _proper_nouns, _words
from .frame import TurnFrame, CONFIDENCE_FLOOR

if TYPE_CHECKING:
    from ...turns.voice.call import SessionCall

# Where a stated turn holds a second fact: "going to Goa and my husband has a heart condition", "with my son who uses a wheelchair".
CLAUSE_BREAK = re.compile(r"[,;.!?]|\b(?:and|but|also|plus|aur|y|with|who|whose|which|because|since|so|while|after)\b", re.I)


def stated_fact_irrelevant(stated: str, frame: Optional[TurnFrame]) -> bool:
    """A stated turn ("my car was hit") may be left out of a shared question only when the model is
    sure of the turn (not abstaining, at or above the confidence floor) and tags the fact as not
    changing this answer, and only when neither the stated words nor the model's type say allergy,
    medication, pregnancy or age (the floor). Late, failed, unsure or silent: the fact counts. Each clause
    of a stated turn is a fact of its own and needs its own "does not change" entry."""
    if frame is None or frame.abstain or frame.confidence < CONFIDENCE_FLOOR or _high_risk(stated):
        return False
    return all(_clause_irrelevant(clause, frame) for clause in _clauses(stated))


def _clause_irrelevant(clause: str, frame: TurnFrame) -> bool:
    stems = _content_stems(clause)
    about = [f for f in frame.fact_relevance if stems & _content_stems(f.fact)]
    return bool(about) and not any(f.changes_answer or f.type in HIGH_RISK_FACT_TYPES for f in about)


def _clauses(stated: str) -> List[str]:
    """The parts of a stated turn that say something (at least one content word)."""
    return [part for part in CLAUSE_BREAK.split(stated) if part and _content_stems(part)] or [stated]


def _content_stems(text: str) -> Set[str]:
    return {_stem(word) for word in _toks(text) if word not in _FUNCTION and len(word) > 2}


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
    said_words: Set[str] = {_rewrite_stem(word) for word in _words(text)}
    return any(_rewrite_stem(name) not in said_words for name in _proper_nouns(rewritten))


def _rewrite_stem(word: str) -> str:
    """A word without case or a plural "s", so "Sunday" in a rewrite matches "sundays" said."""
    return word.lower().rstrip("s")
