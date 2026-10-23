"""The word rules for high-risk stated facts: an allergy, a medication, a pregnancy, an age, a serious condition. A
shared answer is never given without such a fact once the caller has stated it, whatever a model says."""

from __future__ import annotations

from typing import List

from .call_context import _AGE_WORDS, _TREATMENTS
from .text import _words

# The fact types that always change an answer (the floor under StatedFacts' relevance).
HIGH_RISK_FACT_TYPES = frozenset({"allergy", "medication", "pregnancy", "age"})

# "I'm allergic to peanuts", "intolerant to lactose".
_ALLERGY_WORDS = frozenset(
    {"allergic", "allergy", "allergies", "intolerant", "intolerance", "anaphylaxis", "anaphylactic", "celiac", "coeliac"}
)
# "I'm on insulin", "she takes warfarin": a treatment, a dose, or a common drug by name.
_MEDICATION_WORDS = _TREATMENTS | frozenset(
    {"prescription", "prescribed", "dose", "dosage", "tablets", "meds", "warfarin", "metformin", "aspirin", "ibuprofen",
     "paracetamol", "acetaminophen", "statin", "statins", "lisinopril", "amoxicillin", "penicillin", "prednisone",
     "levothyroxine", "antidepressants", "ssri", "opioids", "morphine", "inhaler", "chemo"}
)
# "I'm diabetic", "he had a stroke": a condition that changes what is safe for the caller.
_CONDITION_WORDS = frozenset(
    {"diabetic", "diabetes", "kidney", "kidneys", "renal", "epilepsy", "epileptic", "seizure", "seizures", "asthma",
     "asthmatic", "stroke", "heart", "cardiac", "cancer", "hypertension", "cirrhosis", "liver", "hiv", "pacemaker",
     "copd", "dementia", "alzheimer", "alzheimers", "arthritis", "thyroid", "anemia", "anaemia", "hemophilia",
     "immunocompromised", "lupus", "crohn", "crohns", "deaf", "blind", "wheelchair", "disabled", "disability", "autism", "autistic", "adhd", "pill", "transplant", "sclerosis", "parkinson", "parkinsons"}
)
# "I'm pregnant", "breastfeeding", "estoy embarazada", "8 months along".
_PREGNANCY_WORDS = frozenset(
    {"pregnant", "pregnancy", "expecting", "trimester", "breastfeeding", "nursing", "postpartum", "embarazada",
     "embarazo", "garbhvati", "pregnent"}
)
_PREGNANCY_PHRASES = (("months", "along"), ("weeks", "along"), ("weeks", "pregnant"), ("months", "pregnant"))
# "a toddler", "she is elderly": an age by its stage.
_AGE_STAGE_WORDS = frozenset(
    {"aged", "toddler", "infant", "baby", "newborn", "elderly", "senior", "teenager", "teen", "yo", "yrs"}
)
# Who an age may be said of ("my son is 3", "she is 80"): a person word next to a number makes it an age.
_PERSON_WORDS = frozenset(
    {"i", "im", "he", "she", "hes", "shes", "son", "daughter", "kid", "kids", "child", "children", "boy", "girl",
     "mother", "father", "mom", "mum", "dad", "grandmother", "grandfather", "grandma", "grandpa", "wife", "husband",
     "brother", "sister", "hijo", "hija", "beta", "beti", "bacha", "bachcha", "bachche",
     "nephew", "niece", "grandson", "granddaughter", "twins", "twin", "cousin", "toddler", "ella", "el", "usko"}
)
# Numbers said in words ("my daughter is three").
_NUMBER_WORDS = frozenset(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
    # Spanish and Hindi ("tres años", "paanch saal"); Hindi "do" (two) is left out: it is English "do".
    "uno dos tres cuatro cinco seis siete ocho nueve diez veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa ek teen char paanch chhe saat aath nau das bees pachaas assi".split()
)


def _is_number(word: str) -> bool:
    return word.isdigit() or word in _NUMBER_WORDS or (word[:-2].isdigit() and word.endswith("yo"))


def _high_risk(text: str) -> bool:
    """The text states an allergy, a medication, a serious condition, a pregnancy or an age."""
    words: List[str] = _words(text)
    named = (_ALLERGY_WORDS, _MEDICATION_WORDS, _CONDITION_WORDS, _PREGNANCY_WORDS, _AGE_STAGE_WORDS)
    if any(w in group for w in words for group in named):
        return True
    if any(words[i:i + 2] == list(phrase) for phrase in _PREGNANCY_PHRASES for i in range(len(words) - 1)):
        return True
    has_number = any(_is_number(w) for w in words)
    return has_number and any(w in _AGE_WORDS or w in _PERSON_WORDS for w in words)
