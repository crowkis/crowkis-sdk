"""The word rules for high-risk stated facts: an allergy, a medication, a pregnancy, an age. A shared
answer is never given without such a fact once the caller has stated it, whatever a model says."""

from __future__ import annotations

from .call_context import _AGE_WORDS, _TREATMENTS
from .text import _words

# The fact types that always change an answer (the floor under StatedFacts' relevance).
HIGH_RISK_FACT_TYPES = frozenset({"allergy", "medication", "pregnancy", "age"})

# "I'm allergic to peanuts", "intolerant to lactose".
_ALLERGY_WORDS = frozenset(
    {"allergic", "allergy", "allergies", "intolerant", "intolerance", "anaphylaxis", "anaphylactic", "celiac", "coeliac"}
)
# "I'm on insulin", "she takes blood thinners".
_MEDICATION_WORDS = _TREATMENTS | frozenset({"prescription", "prescribed", "dose", "dosage", "tablets", "meds"})
# "I'm pregnant", "breastfeeding".
_PREGNANCY_WORDS = frozenset(
    {"pregnant", "pregnancy", "expecting", "trimester", "breastfeeding", "nursing", "postpartum"}
)
# "my 3 year old", "a toddler", "she is 80": an age, or a word that is one.
_AGE_STAGE_WORDS = frozenset({"aged", "toddler", "infant", "baby", "newborn", "elderly", "senior", "teenager", "teen"})


def _high_risk(text: str) -> bool:
    """The text states an allergy, a medication, a pregnancy or an age."""
    words = _words(text)
    if any(w in _ALLERGY_WORDS or w in _MEDICATION_WORDS or w in _PREGNANCY_WORDS or w in _AGE_STAGE_WORDS
           for w in words):
        return True
    return any(w.isdigit() for w in words) and any(w in _AGE_WORDS for w in words)
