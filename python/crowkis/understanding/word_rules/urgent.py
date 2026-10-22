"""Crisis and urgent turns: self-harm, poisoning, injury, collapse, assault."""

from __future__ import annotations

from typing import List

from .text import (  # noqa: F401
    _RELATIONS,
    _first_words,
    _has_phrase,
)
from .phrases import (  # noqa: F401
    _CRISIS_PHRASES,
)


_CRISIS_PHRASES_BY_FIRST = _first_words(_CRISIS_PHRASES)


# An emergency or a crisis, in the languages callers use (English, Hindi/Hinglish,
# Spanish, Portuguese, French), found by its shape rather than by fixed sentences.
# Word starts that are always one: "suicidal", "overdosed", "behosh", "desmayó".
_EMERGENCY_STEMS = (
    "suicid", "overdos", "sobredos", "envenen", "behosh", "unconscious", "inconscien", "desmay",
    "desmai", "évanoui", "evanoui", "fainted", "collapsed", "convuls", "seizure", "choking",
    "atragant", "engasg", "étouff", "drowning", "ahogand", "afogand", "bleeding", "sangrand",
    "khudkushi", "aatmahatya", "atmahatya", "infarto", "poisoned", "poisoning", "electrocut",
)


_EMERGENCY_PHRASES = (
    ("heart", "attack"), ("not", "breathing"), ("no", "respira"), ("não", "respira"), ("nao", "respira"),
    ("ne", "respire"), ("saans", "nahi"), ("saans", "nahin"), ("dil", "ka", "daura"), ("crise", "cardiaque"),
    ("chest", "pain"), ("dolor", "de", "pecho"), ("dor", "no", "peito"), ("seene", "mein", "dard"),
    ("cut", "myself"), ("cutting", "myself"), ("hurt", "myself"), ("hurting", "myself"),
    ("harm", "myself"), ("harming", "myself"), ("burn", "myself"), ("burned", "myself"),
    ("me", "corté"), ("me", "corte"), ("me", "corto"), ("me", "cortei"), ("me", "cortar"),
    ("me", "matar"), ("me", "mato"), ("me", "tuer"), ("me", "couper"), ("khud", "ko"),
    ("cortarme",), ("matarme",), ("lastimarme",), ("suicidarme",), ("having", "a", "stroke"),
    ("had", "a", "stroke"), ("khoon", "nikal"),
)


_EMERGENCY_PHRASES_BY_FIRST = _first_words(_EMERGENCY_PHRASES)


# A wish to die ("i want to die", "quiero morir", "marna chahta hoon"), or not to
# live ("i don't want to live anymore", "jeena nahi chahta"), in any word order.
_WANTS = frozenset(
    {"want", "wanna", "going", "gonna", "quiero", "quero", "veux", "voudrais", "chahta", "chahti", "chahte", "ganas"}
)


_DYING = frozenset({"die", "dying", "morir", "morirme", "morrer", "mourir", "marna", "marne", "maut"})


_LIVING = frozenset({"live", "living", "vivir", "viver", "vivre", "jeena", "jeene", "jina"})


_NEGATIONS = frozenset({"don", "dont", "not", "no", "never", "não", "nao", "ne", "nahi", "nahin", "na"})


# Harm turned on oneself, in any form: "cutting myself", "she keeps harming herself".
_HARMS = ("cut", "hurt", "harm", "kill", "burn", "stab", "starv", "hang", "poison")


_REFLEXIVES = frozenset({"myself", "herself", "himself", "themselves", "ourselves", "yourself"})


# Something swallowed or drunk that must not be: "mere bete ne kerosene pee liya".
_SUBSTANCES = frozenset(
    {
        "kerosene", "kerosine", "bleach", "pesticide", "insecticide", "poison", "acid", "phenyl",
        "phenol", "detergent", "veneno", "lejía", "lejia", "cloro", "javel", "battery", "batteries",
        "pila", "pilas", "bateria", "baterias", "pills", "tablets", "pastillas", "pastilhas",
        "comprimidos", "cachets", "goli", "goliyan", "dawai",
    }
)


_INGESTED = frozenset(
    {
        "swallowed", "swallow", "swallowing", "drank", "drunk", "ate", "eaten", "took", "taken",
        "ingested", "pee", "piya", "pi", "peeli", "kha", "khaa", "khali", "khaya", "nigal", "nigla",
        "nigli", "tragó", "trago", "tragado", "tragada", "bebió", "bebio", "tomó", "comió", "comio",
        "engoliu", "engoli", "bebeu", "tomou", "comeu", "avalé", "avale", "bu", "mangé",
    }
)


# Hurt, or attacked, said of someone: "bhai ka accident ho gaya", "my dad fell".
_INJURIES = frozenset(
    {
        "accident", "accidente", "acidente", "burn", "burned", "burnt", "quemado", "quemada", "quemó",
        "queimou", "queimado", "brûlé", "fracture", "fractured", "fractura", "fratura", "injured",
        "hurt", "herido", "herida", "ferido", "ferida", "blessé", "blessée", "bitten", "mordido",
        "stabbed", "shot", "chot", "fell", "gir", "gira", "giri", "gire", "caí", "cayó", "caiu", "tombé",
        "assaulted", "assault", "attacked", "mugged", "beaten", "agredido", "agredida", "agrediu",
        "agressé", "agressée", "golpeó", "golpearon", "maara", "maari", "peeta", "peeti",
    }
)


# Who or when: the event happened to someone ("ho gaya", "my", "papa", "she").
_EVENT_MARKERS = frozenset(
    {
        "ho", "gaya", "gayi", "gaye", "hua", "hui", "happened", "had", "met", "got", "was", "were",
        "i", "me", "my", "we", "our", "he", "she", "his", "her", "him", "they", "mera", "meri",
        "mere", "mujhe", "yo", "mi", "eu", "meu", "minha", "mon", "ma", "je", "tuvo", "teve",
        "papa", "mummy", "mom", "mum", "dad", "beta", "beti", "bete", "bhai", "behen", "didi",
    }
)


def _urgent(words: List[str]) -> bool:
    """An emergency or a crisis: self-harm, poisoning, injury, collapse, heart or assault."""
    if _has_phrase(words, _CRISIS_PHRASES_BY_FIRST) or _has_phrase(words, _EMERGENCY_PHRASES_BY_FIRST):
        return True
    if any(w.startswith(_EMERGENCY_STEMS) for w in words):
        return True
    if any(w in _REFLEXIVES and any(v.startswith(_HARMS) for v in words[max(0, i - 2):i]) for i, w in enumerate(words)):
        return True
    if any(w in _SUBSTANCES for w in words) and any(w in _INGESTED for w in words):
        return True
    if any(w in _INJURIES for w in words) and any(w in _EVENT_MARKERS or w in _RELATIONS for w in words):
        return True
    for index in range(len(words)):
        near = words[index:index + 4]
        if any(w in _WANTS for w in near) and any(w in _DYING for w in near):
            return True
        wider = words[index:index + 6]
        if any(w in _NEGATIONS for w in wider) and any(w in _WANTS for w in wider) and any(
            w in _LIVING and (w not in ("live", "living") or (at > 0 and wider[at - 1] == "to"))  # not "live chat"
            for at, w in enumerate(wider)
        ):
            return True
    return False
