"""What the caller told the call: conditions, plans, instructions, steps of their own task."""

from __future__ import annotations

from typing import List

from .personal import _describes_caller, _diagnosis, _discloses, _sensitive_self, _unreadable
from .text import (
    _AMOUNT_WORDS,
    _CALLER_KINDS,
    _DISCOURSE,
    _MATTERS,
    _NUMBER_WORDS,
    _OTHER_POSSESSIVES,
    _POSSESSIVES,
    _QUESTION_LEADS,
    _WH_WORDS,
    _clause_starts,
    _contains,
    _first_words,
    _has_digit,
    _has_phrase,
    _proper_nouns,
    _words,
    _ACTION_LEADS_BY_FIRST,
    _SOMEONE,
    _STEERING,
)
from .urgent import _urgent

# What a caller tells the call can change the right answer to a later question
# ("I'm allergic to peanuts", then "is pad thai safe?"). The later question alone
# does not say so, so after such a turn nothing in the call is looked up or shared.
_BIRTH_WORDS = frozenset(
    {"born", "birth", "dob", "birthday", "nasci", "naci", "nací", "nacido", "nacida", "nascido",
     "nascida", "né", "née", "paida", "janam"}
)


# What the caller is, has or plans: "I'm vegetarian", "I am 65", "we're travelling".
_SELF_STATES = (("i", "am"), ("i", "m"), ("we", "are"), ("we", "re"), ("soy",), ("estoy",), ("main",), ("je", "suis"))


_HAVING = (("i", "have"), ("we", "have"), ("i", "ve", "got"), ("we", "ve", "got"), ("tengo",), ("mujhe",))


_MY = _POSSESSIVES | _OTHER_POSSESSIVES | {"mera", "meri", "mere"}


# Said after "I'm" or "I have", each of these is something about the caller that can change an answer.
_SELF_ATTRIBUTES = frozenset(
    {"vegetarian", "vegan", "pescatarian", "diabetic", "allergic", "pregnant", "lactose", "gluten",
     "celiac", "coeliac", "intolerant", "retired", "disabled", "deaf", "blind", "married", "single",
     "divorced", "widowed", "unemployed", "employed", "pensioner", "senior", "student", "beginner",
     "expert", "elderly", "nursing", "breastfeeding", "shakahari", "vegetariano", "vegetariana",
     "vegano", "vegana", "diabético", "diabética", "alérgico", "alérgica", "embarazada", "estudiante",
     "jubilado", "jubilada", "né", "née", "nacido", "nacida", "self", "migraine", "migraines", "arthritis",
     "hypertension", "cholesterol", "thyroid", "epilepsy", "fever", "flu", "cough", "headache", "injury",
     "surgery", "eczema", "psoriasis", "ulcer", "bp", "sugar", "keto", "halal", "kosher", "pacemaker",
     "implant", "stent"}
)


# "I'm travelling to Goa": a plan, only with where to ("I'm planning to cancel" is not one).
_PLAN_VERBS = frozenset(
    {"visiting", "planning", "travelling", "traveling", "moving", "relocating", "flying", "going", "hosting"}
)


# "I'm 5 minutes away", "we're 10 minutes late": a number that is not an age.
_NOT_AGE_UNITS = frozenset(
    {"minute", "minutes", "mins", "min", "hour", "hours", "hrs", "second", "seconds", "secs", "km", "kms",
     "mile", "miles", "meters", "metres", "blocks", "day", "days", "week", "weeks", "orders", "items",
     "steps", "times", "percent", "pm", "am"}
)


_AGE_WORDS = frozenset({"year", "years", "yr", "yrs", "old", "saal", "años", "ans", "anos"})


# Doing something to the caller's own booking, order or account ("change my flight",
# "cancel my order"): the turns after it are steps in that task. Looking at it ("check my
# order", "track my parcel") is not.
_CHANGE_VERBS = frozenset(
    {"cancel", "book", "reschedule", "change", "update", "delete", "remove", "transfer", "refund", "replace",
     "exchange", "return", "upgrade", "downgrade", "activate", "deactivate", "close", "renew", "reserve",
     "move", "modify", "rebook", "postpone", "extend", "pause", "resume", "block", "unblock"}
)


# "I'm on blood thinners": a treatment the caller is on.
_TREATMENTS = frozenset(
    {"blood", "medication", "medicine", "medicines", "insulin", "dialysis", "chemo", "chemotherapy",
     "antibiotics", "steroids", "thinners", "pills", "treatment", "oxygen"}
)


_ARTICLE_FILLERS = frozenset({"bit", "little", "lot", "few", "couple"})


_GENERIC_ROLES = frozenset({"customer", "customers", "user", "users", "buyer", "client", "guest", "visitor", "shopper"})


# "I have a question" asks; "I have a 3 year old daughter" tells.
_HAVE_NOT = frozenset(
    {"question", "questions", "query", "doubt", "quick", "general", "problem", "issue", "complaint",
     "request", "minute", "moment", "second", "look", "few", "couple", "idea", "feeling", "bit", "more",
     "thing", "things", "pregunta", "duda", "problema", "momento", "queja"}
)


_PLANS = frozenset({"trip", "vacation", "holiday", "wedding"})


# Part of the caller's life: told about, it can change an answer.
_LIFE_WORDS = frozenset(
    {"income", "salary", "age", "family", "wife", "husband", "son", "daughter", "kids", "children",
     "child", "baby", "parents", "mother", "father", "mom", "mum", "dad", "farm", "business", "company",
     "shop", "health", "condition", "disability", "pension", "loan", "debt", "religion", "diet", "budget",
     "partner", "grandmother", "grandfather", "sister", "brother", "kid", "dog", "cat", "pet", "beta",
     "beti", "maa", "papa", "umar", "bachche", "bacha", "hijo", "hija", "hijos", "madre", "padre",
     "esposa", "esposo", "edad", "newborn", "twins", "dogs", "cats", "pets", "diet"}
) | _PLANS


# "my loan is not showing": a problem with the thing, not a fact about the caller.
_NOT_TOLD = frozenset(
    {"not", "no", "still", "showing", "missing", "pending", "stuck", "blocked", "late", "delayed", "down",
     "broken", "wrong", "gone"}
)


# "my son is 12", "my budget is", "mera beta 12 saal ka hai": a life word told, not asked about.
_TELLING_VERBS = frozenset(
    {"is", "s", "has", "was", "are", "have", "had", "needs", "takes", "lives", "works", "eats", "hai",
     "es", "tiene"}
)


# How the caller wants answers from now on ("reply only in Hindi", "keep it short"), or what
# they live by ("I don't eat meat"). Counted only where a clause starts, so "can I keep it"
# and "is it available only in red" are not instructions.
_INSTRUCTIONS = _STEERING + (
    ("reply", "in"), ("reply", "only"), ("respond", "in"), ("respond", "only"), ("answer", "in"),
    ("answer", "only"), ("speak", "in"), ("talk", "in"), ("talk", "to", "me", "in"), ("write", "in"),
    ("keep", "it"), ("keep", "answers"), ("keep", "your"), ("explain", "like"),
    ("speak", "slowly"), ("speak", "slower"), ("use", "metric"), ("responde", "en"), ("habla", "en"),
    ("i", "don", "t", "eat"), ("i", "do", "not", "eat"), ("we", "don", "t", "eat"), ("i", "take"),
    ("i", "earn"), ("we", "earn"), ("i", "only", "speak"), ("i", "don", "t", "speak"), ("i", "was", "born"),
    ("talk", "to", "me", "like"), ("vivo", "en"), ("i", "can", "t", "have"), ("i", "cannot", "have"),
    ("i", "keep", "halal"), ("i", "keep", "kosher"), ("i", "live", "alone"), ("i", "live", "with"),
)


# Said anywhere: "mujhe Hindi mein jawab do".
_INSTRUCTIONS_ANYWHERE = (("mein", "jawab"), ("mein", "baat"), ("mein", "bolo"), ("en", "español"), ("en", "inglés"))


_INSTRUCTIONS_ANYWHERE_BY_FIRST = _first_words(_INSTRUCTIONS_ANYWHERE)


# "forget it", "ignore that", "I take it", "speak in a minute", "just keep it": after these
# phrases, a word like these (or nothing) means it is not an instruction.
_NOT_AN_OBJECT = frozenset({"it", "that", "this", "about", "the", "a", "an", "care", "you", "your", "my", "to"})


_NEEDS_AN_OBJECT = frozenset(
    {("forget",), ("ignore",), ("assume",), ("pretend",), ("i", "take"), ("keep", "it"), ("reply", "in"),
     ("respond", "in"), ("answer", "in"), ("speak", "in"), ("talk", "in"), ("write", "in"), ("talk", "to", "me", "in")}
)


def _instructs(text: str, words: List[str]) -> bool:
    if _has_phrase(words, _INSTRUCTIONS_ANYWHERE_BY_FIRST):
        return True
    for start in _clause_starts(text):
        for phrase in _INSTRUCTIONS:
            end = len(phrase)
            if tuple(start[:end]) != phrase:
                continue
            if phrase not in _NEEDS_AN_OBJECT or (end < len(start) and start[end] not in _NOT_AN_OBJECT):
                return True
    return False


def _states_self(text: str, words: List[str]) -> bool:
    places = _proper_nouns(text)
    for index in range(len(words)):
        for lead in _SELF_STATES:
            end = index + len(lead)
            if tuple(words[index:end]) != lead or end >= len(words):
                continue
            x, after = words[end], words[end + 1:end + 3]
            if x in ("a", "an"):
                if after and after[0] not in _ARTICLE_FILLERS and not any(w in _GENERIC_ROLES for w in after):
                    return True
            elif _has_digit(x) or x in _AMOUNT_WORDS:
                if not (after and after[0] in _NOT_AGE_UNITS):
                    return True  # "I'm 65", not "I'm 5 minutes away"
            elif x in _SELF_ATTRIBUTES or x in _CALLER_KINDS:
                return True
            elif x in _PLAN_VERBS:
                if any(w in _PLANS or w in places or w in _LIFE_WORDS for w in words[end + 1:end + 5]):
                    return True  # "I'm travelling to Goa", not "I'm planning to cancel"
            elif x in ("in", "from", "de") and after and after[0] in places:
                return True  # "I'm in Pune"
            elif x == "on" and any(w in _TREATMENTS or w in _SELF_ATTRIBUTES or w == "diet" for w in words[end + 1:end + 4]):
                return True  # "I'm on blood thinners", "I'm on a keto diet"
        for lead in _HAVING:
            end = index + len(lead)
            if tuple(words[index:end]) != lead or end >= len(words):
                continue
            told = words[end:end + 6]
            if any(w in _HAVE_NOT for w in told):
                continue
            if any(w in _LIFE_WORDS or w in _MATTERS or w in _SELF_ATTRIBUTES for w in told):
                return True  # "I have two kids", "I have a 3 year old daughter"
            if any(_has_digit(w) or w in _AMOUNT_WORDS for w in told) and any(w in _AGE_WORDS for w in told):
                return True  # "tengo 65 años"; "I have 2 orders pending" is not
        if words[index] in _MY and index + 2 < len(words) and words[index + 1] in _LIFE_WORDS:
            told = words[index + 2]
            then = words[index + 3] if index + 3 < len(words) else ""
            if told == "s":  # "my wife's card" is not "my wife is ..."
                told = then if _has_digit(then) or then in _NUMBER_WORDS else ""
            if (told in _TELLING_VERBS and then not in _NOT_TOLD) or _has_digit(told) or told in _NUMBER_WORDS:
                return True
    return False


def _acts_on_own(words: List[str]) -> bool:
    """"I want to change my flight", "cancel my order": a step in the caller's own task,
    with "my" right after what is to be done. "Let me check my email" is the caller's."""
    lead = next((w for w in words if w not in _DISCOURSE), None)
    asks_for = _has_phrase(words, _ACTION_LEADS_BY_FIRST) and not _contains(words, ("let", "me"))
    if not (asks_for or lead in _CHANGE_VERBS):
        return False
    return any(
        w in _CHANGE_VERBS and any(o in _POSSESSIVES for o in words[i + 1:i + 3])
        for i, w in enumerate(words)
    )


def _describes_self(words: List[str]) -> bool:
    """The live rule's "who the caller is", less "I'm on ...": "I'm on hold" and "I'm on
    the website" say where the call is, not who is calling ("I'm on the premium plan"
    still counts through the plan's name)."""
    on = _contains(words, ("i", "m", "on")) or _contains(words, ("i", "am", "on"))
    return _describes_caller(words) and (not on or any(w in _CALLER_KINDS for w in words))


def _sets_context(text: str) -> bool:
    """Whether this turn tells the call something later answers may depend on, said
    on its own or inside a question: a health, legal or money matter, an emergency,
    a step in the caller's own task, what the caller is, has or plans ("I'm
    vegetarian", "I have a 3 year old daughter", "I'm planning a trip to Goa"), a
    date of birth, or how to answer from now on ("reply only in Hindi"). Each is a
    match on what was said, never a default: small talk, "I have a question",
    "I'm frustrated", "I have 2 orders" and a name or number change no answer, and a call that starts
    with them keeps its shared answers."""
    words = _words(text)
    return _tells_facts(text) or (bool(words) and _instructs(text, words))


def _tells_about_caller(text: str) -> bool:
    """``_tells_facts`` for a chat's memory and its emergency check: a question that only asks
    about a matter ("what are the symptoms of a heart attack?", "how do I treat a burn?") tells
    nothing about the caller. What the caller is or has, said inside a question ("what should I
    eat, I'm diabetic?"), still counts."""
    words = _words(text)
    if words and (words[0] in _WH_WORDS or words[0] in _QUESTION_LEADS) and not any(
            w in _POSSESSIVES or w in _SOMEONE for w in words):
        return _describes_self(words) or _states_self(text, words) or any(w in _BIRTH_WORDS for w in words)
    return _tells_facts(text)


def _tells_facts(text: str) -> bool:
    """``_sets_context`` without instructions: what the caller is, has, plans or is doing
    about their own task. A later shared question must carry these; a "reply in Hindi"
    is carried by the reply language instead."""
    words = _words(text)
    return bool(words) and (
        _unreadable(text) or _discloses(words) or _sensitive_self(words) or _urgent(words)
        or (_diagnosis(words) and not any(w in _HAVE_NOT for w in words)
            and not any(_contains(words, (have, article)) for have in ("have", "tengo")
                        for article in ("a", "an", "un", "una", "el", "la")))
        or _acts_on_own(words) or _describes_self(words) or _states_self(text, words)
        or any(w in _BIRTH_WORDS for w in words)
    )


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
_HIGH_RISK_NUMBER_WORDS = frozenset(
    "one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen "
    "eighteen nineteen twenty thirty forty fifty sixty seventy eighty ninety hundred "
    # Spanish and Hindi ("tres años", "paanch saal"); Hindi "do" (two) is left out: it is English "do".
    "uno dos tres cuatro cinco seis siete ocho nueve diez veinte treinta cuarenta cincuenta sesenta setenta ochenta noventa ek teen char paanch chhe saat aath nau das bees pachaas assi".split()
)


def _is_number(word: str) -> bool:
    return word.isdigit() or word in _HIGH_RISK_NUMBER_WORDS or (word[:-2].isdigit() and word.endswith("yo"))


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
