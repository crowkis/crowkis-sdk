"""The word rules: fixed English word and phrase checks that read a caller's turn or a
model's answer (personal, a follow-up, cut off, sets context, a non-answer, repeats a
caller's detail, ...). Moved unchanged from voice.py in v4 P1; voice.py re-exports every
name, so ``crowkis.voice._is_personal`` and the others keep working. The question, hit and
save rules (crowkis.rules) read a turn through these checks."""

from __future__ import annotations

import collections
import hashlib
import inspect
import json
import logging
import re
import string
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union

_TRIM = string.punctuation + string.whitespace


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


_SLOT = re.compile(r"\{([^{}\s]+)\}")


_CONTEXT_BOUND_THRESHOLD = 0.995


# Text written for a screen: a link, code, or markup a voice would read out.
_UNSPEAKABLE = re.compile(
    r"https?://|www\.|`|\]\(|\*\*|^\s*(?:#{1,6}\s|\|)", re.MULTILINE | re.IGNORECASE
)


# How a cached answer that commits the business (a price, a refund, a policy)
# may be spoken. Only matters when the server's decision engine flags one.
_COMMITMENTS = {
    "serve": lambda hit: True,
    "exact": lambda hit: bool(hit.get("exact")),
    "never": lambda hit: False,
}


def _first_words(phrases) -> Dict[str, List[tuple]]:
    """A phrase table keyed by first word, built once at import: a turn is then
    checked word by word against the few phrases that can start there."""
    index: Dict[str, List[tuple]] = {}
    for phrase in phrases:
        index.setdefault(phrase[0], []).append(tuple(phrase))
    return index


def _has_phrase(words: List[str], index: Dict[str, List[tuple]]) -> bool:
    """Whether any phrase of the table occurs in the turn (as `_contains` on each, faster)."""
    for start, word in enumerate(words):
        for phrase in index.get(word, ()):
            if tuple(words[start:start + len(phrase)]) == phrase:
                return True
    return False


def _speakable(text: str) -> bool:
    return not _UNSPEAKABLE.search(text or "")


_POSSESSIVES = frozenset({"my", "our", "mine", "ours"})


# "My" in the other Latin-script languages callers use: Hinglish, French, Spanish,
# Portuguese, German, Italian, Dutch. Followed by a noun, the same rule as "my order".
# German "mein" is left out: in Hinglish it means "in" ("299 wale mein?").
_OTHER_POSSESSIVES = frozenset(
    {
        "humara", "humari", "humare", "hamare", "apna", "apni", "apne", "mai",
        "ma", "mon", "mes", "notre", "mi", "mis", "nuestro", "nuestra", "nuestros", "nuestras",
        "meu", "minha", "meus", "minhas", "nosso", "nossa", "meine", "meinen", "meinem",
        "meiner", "unser", "unsere", "mio", "mia", "miei", "mijn",
    }
)


# Whose a thing is: the caller's, or another person's ("her test results").
_OWNERS = _POSSESSIVES | _OTHER_POSSESSIVES | {"his", "her", "hers", "their", "theirs"}


_FIRST_PERSON = frozenset({"i", "me", "my", "mine", "myself", "we", "us", "our", "ours"})


_PROCEDURAL = (
    ("how", "do", "i"),
    ("how", "do", "we"),
    ("how", "to"),
    ("how", "can", "i"),
    ("how", "can", "we"),
    ("steps", "to"),
    ("where", "do", "i"),
    ("can", "i"),
    ("can", "we"),
    ("is", "there", "a", "way"),
    ("walk", "me", "through"),
    ("help", "me"),
    ("guide",),
    ("tutorial",),
    ("what", "should", "i", "do"),
    ("what", "do", "i", "do"),
    ("what", "can", "i", "do"),
    ("what", "are", "the", "steps"),
    ("how", "long", "do", "i", "have"),
    ("what", "is", "the", "process"),
    ("what", "happens", "if"),
    ("what", "should", "i", "bring"),
    ("what", "should", "i", "expect"),
    ("what", "should", "i", "prepare"),
    ("what", "should", "i", "ask"),
    ("what", "do", "i", "need", "to", "bring"),
)


# After "can i", these ask for something for the caller ("can i get a refill of
# my prescription"), not how something is done.
_REQUEST_VERBS = frozenset(
    {
        "get", "have", "receive", "collect", "pick", "order", "book", "reserve", "renew",
        "refill", "extend", "claim", "redeem", "take",
    }
)


_OWNER_PREPOSITIONS = frozenset(
    {
        "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
        "onto", "under", "via",
    }
)


_STATE_LEADS = frozenset(
    {
        "what", "whats", "when", "where", "which", "who", "how", "is", "are",
        "has", "have", "had", "did", "do", "does", "show", "tell", "check",
        "status",
    }
)


_CONNECTIVES = frozenset({"and", "so", "but", "or", "also", "then", "aur", "phir", "lekin", "toh"})


_CONNECTIVE_PAIRS = frozenset({"what about", "how about", "ok and", "okay and"})


_ELLIPSIS_LEADS = frozenset(
    {"for", "with", "about", "in", "on", "at", "to", "from", "by"}
)


# A preposition-led utterance is a fragment only when nothing after it forms a
# clause: "for ten people" borrows its verb, "in python, how do i ..." brings one.
_CLAUSE_MARKERS = frozenset(
    {
        "what", "how", "why", "when", "where", "which", "who", "whose", "is", "are",
        "was", "were", "do", "does", "did", "can", "could", "should", "would", "will",
        "explain", "describe", "define", "list", "show", "tell", "give", "compare",
        "write", "summarise", "summarize", "translate",
    }
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


_FUNCTION_WORDS = frozenset(
    {
        "a", "about", "am", "an", "and", "any", "are", "as", "at", "be", "been",
        "but", "by", "can", "could", "did", "do", "does", "for", "from", "how",
        "i", "if", "in", "is", "it", "many", "me", "much", "my", "no", "not",
        "of", "ok", "okay", "on", "one", "or", "our", "please", "should", "so",
        "that", "the", "their", "them", "then", "there", "these", "they",
        "this", "those", "to", "us", "was", "were", "what", "whats", "when",
        "where", "which", "who", "why", "will", "with", "would", "you", "your",
    }
)


# Words that say how to choose, not what about: a turn made only of these and
# function words ("which is cheaper", "what do i do now") borrows its subject.
_BARE = frozenset(
    {
        "cheaper", "cheapest", "better", "best", "faster", "fastest", "quicker", "more",
        "less", "bigger", "smaller", "difference", "different", "same", "recommend",
        "prefer", "option", "options", "choice", "ones", "else", "other", "others",
        "between", "both", "either", "neither", "worth", "now", "next", "help", "good",
        "bad", "s", "d", "ll", "re", "ve", "m", "t",
    }
)


def _normalise(text: str) -> str:
    return " ".join((text or "").strip(_TRIM).lower().split())


def _words(text: str) -> List[str]:
    return _WORDS.findall((text or "").lower())


# Which question a shared answer was saved for, kept beside it as a plain key (keyed by
# the answer, per tenant), so a hit can be checked against the question it really answers.
# A plain GET/SET key, not the tool cache: that is an Enterprise feature.
_QUESTION_KEY = "crowkis:question:{tenant}:{answer}"


# Words that change how a question is put, not what it asks about.
_FRAMING_WORDS = frozenset(
    {"what", "when", "where", "which", "who", "whom", "whose", "why", "you", "your", "yours",
     "we", "us", "tell", "know", "like", "want", "need", "help", "get", "got", "have", "has",
     "had", "give", "show", "find", "let", "would", "will", "may", "might", "must", "just",
     "also", "really", "kindly", "hi", "hello", "hey", "thanks", "thank", "question",
     "kya", "kab", "kahan", "kaise", "kaun", "kyun", "kyon", "kitna", "kitne", "kitni", "hai",
     "hain", "ho", "hun", "hoon", "aap", "tum", "ko", "ka", "ki", "ke", "se", "par", "bhi", "toh"}
)


def _stem(word: str) -> str:
    if word.endswith("es") and word[:-2].endswith(("s", "x", "z", "ch", "sh")) and len(word) >= 5:
        return word[:-2]  # "boxes", "dishes"; "prices" and "rates" just drop the "s"
    for suffix, keep in (("ies", "y"), ("ing", ""), ("ed", ""), ("s", "")):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3 and not word.endswith("ss"):
            return word[: len(word) - len(suffix)] + keep
    return word


def _content_words(text: str) -> set:
    return {_stem(w) for w in _words(text) if w not in _FUNCTION_WORDS and w not in _FRAMING_WORDS}


def _different_specifics(asked: str, stored: str) -> bool:
    """Two questions about different things: each has content words the other does
    not ("on Saturday" / "on Sunday", "the city museum" / "the riverside greenhouse").
    A rewording only adds or drops words on one side ("when are you open" / "what
    are your opening hours"), or changes how it asks ("can I" / "do I")."""
    a, s = _content_words(asked), _content_words(stored)
    return bool(a - s) and bool(s - a)


# Question words in front of a pronoun that are not what it refers to: "how long
# does it take" still needs the previous turn to say what "it" is.
_NON_REFERENTS = frozenset(
    {
        "long", "often", "far", "soon", "fast", "quickly", "early", "late",
        "exactly", "usually", "still", "also", "really", "actually",
    }
)


# After "that" or "those", these make it a pronoun rather than a determiner:
# "what does that cost", "is that refundable", as opposed to "that plan".
_PRONOUN_FOLLOWERS = frozenset(
    {
        "cost", "costs", "mean", "means", "take", "takes", "include", "includes",
        "cover", "covers", "work", "works", "apply", "applies", "last", "lasts",
        "come", "comes", "ship", "ships", "free", "available", "included",
        "possible", "refundable", "returnable", "right", "correct", "true", "safe",
        "worth", "enough", "extra", "cheaper", "better",
    }
)


# Who the caller is changes the answer ("as a premium member", "i'm a student",
# "i live in canada", "what plan am i on"), so such a turn is about this caller.
_CALLER_KINDS = frozenset(
    {
        "premium", "gold", "silver", "platinum", "diamond", "vip", "prime", "elite",
        "business", "businesses", "corporate", "enterprise", "wholesale", "student",
        "students", "senior", "seniors", "veteran", "veterans", "military", "teacher",
        "teachers", "employee", "employees", "member", "members", "subscriber",
        "subscribers", "partner", "partners", "reseller", "resellers", "pensioner",
        "pensioners", "retiree", "retirees", "nri",
    }
)


_CALLER_LEADS = (("as", "a"), ("as", "an"), ("i", "am"), ("i", "m"))


_SELF_PHRASES = (
    ("am", "i"), ("do", "i", "qualify"), ("i", "live", "in"), ("i", "am", "from"),
    ("i", "m", "from"), ("i", "am", "based"), ("i", "m", "based"), ("i", "am", "on"),
    ("i", "m", "on"), ("i", "live", "on"), ("i", "live", "at"), ("i", "stay", "in"), ("i", "stay", "at"),
    ("i", "m", "staying"), ("i", "am", "staying"),
)


_SELF_PHRASES_BY_FIRST = _first_words(_SELF_PHRASES)


def _describes_caller(words: List[str]) -> bool:
    if _has_phrase(words, _SELF_PHRASES_BY_FIRST):
        return True
    # "for business accounts, what ..." frames the turn; "the grace period for
    # premium payment" only names a kind of thing.
    if words[:1] == ["for"] and any(w in _CALLER_KINDS for w in words[1:4]):
        return True
    # "what discount do you have for pensioners like me"
    if any(w in _CALLER_KINDS for w in words) and (_contains(words, ("like", "me")) or _contains(words, ("like", "us"))):
        return True
    for index in range(len(words)):
        for lead in _CALLER_LEADS:
            end = index + len(lead)
            if tuple(words[index:end]) == lead and any(w in _CALLER_KINDS for w in words[end:end + 3]):
                return True
    return False


def _contains(words: List[str], phrase: tuple) -> bool:
    span = len(phrase)
    return any(
        tuple(words[start:start + span]) == phrase
        for start in range(len(words) - span + 1)
    )


def _owned_record_at(words: List[str]) -> Optional[int]:
    """Where the turn names something of the caller's or of another person's:
    "my food", "her test results", "our usual table"."""
    for index, word in enumerate(words[:-1]):
        if word in _OWNERS and words[index + 1] not in _FUNCTION_WORDS:
            return index
    # Hinglish "main order kab aayega"; English "main" only ever leads a question
    # through a question word ("what is the main difference").
    if words[:1] == ["main"] and len(words) > 1 and words[1] not in _FUNCTION_WORDS and words[1] not in _MAIN_THINGS and not any(
        w in _WH_WORDS for w in words
    ):
        return 0
    return None


_PROCEDURAL_BY_FIRST = _first_words(_PROCEDURAL)


# After "main", these make it the English adjective: "main branch", "main menu".
_MAIN_THINGS = frozenset(
    {
        "branch", "office", "gate", "entrance", "menu", "road", "door", "store", "page", "course",
        "difference", "reason", "line", "station", "building", "counter", "desk", "hall", "lobby",
        "street", "market", "square", "campus", "hospital", "website", "app", "screen", "number",
        "feature", "features", "plan", "dish", "event", "stage", "switch", "power",
    }
)


def _procedural(words: List[str]) -> bool:
    for start, word in enumerate(words):
        for phrase in _PROCEDURAL_BY_FIRST.get(word, ()):
            span = len(phrase)
            if tuple(words[start:start + span]) != phrase:
                continue
            after = words[start + span] if start + span < len(words) else None
            if phrase[0] == "can" and after in _REQUEST_VERBS:
                continue
            return True
    return False


def _requests(words: List[str]) -> bool:
    """"Can i get ...", "could we book ...": the caller asks for something for themselves."""
    return any(
        words[index] in ("can", "could", "may") and words[index + 1] in ("i", "we")
        and words[index + 2] in _REQUEST_VERBS
        for index in range(len(words) - 2)
    )


def _is_state_interrogative(words: List[str]) -> bool:
    return words[0] in _STATE_LEADS or "status" in words


# Things a caller owns; with a state word after them, a statement about their own item.
_OWNED_THINGS = frozenset(
    {
        "phone", "laptop", "headphones", "earphones", "charger", "shoes", "case", "tv",
        "television", "watch", "smartwatch", "device", "product", "item", "bag", "jacket",
        "shirt", "fridge", "refrigerator", "machine", "tablet", "camera", "speaker",
    }
)


_STATE_WORDS = frozenset(
    {
        "is", "are", "was", "were", "arrived", "came", "stopped", "broke", "broken", "not",
        "isn", "doesn", "won", "has", "got", "cracked", "damaged", "defective", "wrong",
        "missing", "stuck", "keeps",
    }
)


_GREETINGS = frozenset({"hi", "hello", "hey", "namaste", "good", "morning", "afternoon", "evening"})


_INTRO_AFTER_GREETING = (("i", "am"), ("i", "m"), ("this", "is"), ("it", "s"), ("my", "name"))


_SPOKEN_DIGITS = frozenset({"zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"})


_DIGIT_REPEATS = frozenset({"double", "triple"})


_EMAIL_ENDINGS = frozenset({"com", "in", "org", "net", "co", "io"})


_ACTION_VERBS = frozenset(
    {
        "cancel", "book", "reschedule", "change", "update", "delete", "remove", "send", "text",
        "email", "call", "connect", "transfer", "escalate", "refund", "replace", "exchange",
        "return", "speak", "talk", "process", "block", "unblock", "check", "track", "add",
        "apply", "upgrade", "downgrade", "activate", "deactivate", "close", "open", "resend",
        "set", "remind", "schedule", "order", "buy", "pay", "play", "turn", "make", "put",
        "note", "save", "confirm", "reserve", "start", "stop", "create", "arrange", "register",
        "sign", "enrol", "enroll", "renew", "recharge", "pause", "resume", "mute", "wake",
        "dial", "message", "share", "forward", "submit", "file", "raise", "lodge", "report",
        "mark", "log", "bring", "get", "find", "go", "do",
    }
)


# A verb first is a request only when it acts on something ("set a timer", "turn
# off the lights", "cancel my order"). A verb before a noun is search-style
# phrasing: "refund status for john", "return policy for shoes".
_ACTION_OBJECTS = (_FUNCTION_WORDS | {
    "a", "an", "some", "another", "all", "everything", "up", "off", "out", "down", "over",
    "back", "away", "ahead", "his", "her", "our", "my", "me", "us",
}) - {"you", "i", "we", "they"}  # "do you ship abroad" asks, "do it" tells


# After these leads, an action verb is a request for the agent to do something.
_ACTION_LEADS = (
    ("please",), ("can", "you"), ("could", "you"), ("will", "you"), ("would", "you"),
    ("i", "want", "to"), ("i", "d", "like", "to"), ("i", "would", "like", "to"),
    ("i", "need", "to"), ("let", "me"), ("i", "wanna"),
)


_ACTION_LEADS_BY_FIRST = _first_words(_ACTION_LEADS)


# Words in front of a clause that do not change what it is: "okay, book it".
_DISCOURSE = frozenset(
    {
        "please", "kindly", "just", "now", "so", "and", "then", "also", "okay", "ok",
        "alright", "fine", "great", "perfect", "sure", "yes", "yeah", "hey", "hi", "hello",
    }
)


# Replies to the agent, not questions: a reply word first, or an acknowledgement
# ("okay", "fine") not followed by a question, and no wh-question word anywhere.
_REPLY_LEADS = frozenset(
    {
        "yes", "yeah", "yep", "yup", "no", "nope", "nah", "correct", "exactly", "sure",
        # in the other languages callers use
        "oui", "si", "sí", "sim", "ja", "claro", "vale", "exacto", "exato", "certo", "nein", "não",
    }
)


_SOFT_REPLY_LEADS = frozenset(
    {
        "okay", "ok", "alright", "fine", "right", "great", "perfect", "cool", "awesome",
        "done", "deal", "lovely", "excellent", "haan", "theek", "accha", "acha",
    }
)


_QUESTION_LEADS = frozenset(
    {
        "can", "could", "do", "does", "did", "is", "are", "am", "was", "were", "will",
        "would", "should", "may", "shall", "has", "have", "tell", "explain", "describe",
    }
)


_WH_WORDS = frozenset({"how", "what", "when", "where", "which", "who", "why"})


# A statement told to the agent ("the iphone 16 is 10 rupees") is not a question
# whose answer other callers need, and what it asserts is the caller's to assert.
_STATEMENT_SUBJECTS = frozenset(
    {"the", "this", "that", "these", "those", "your", "its", "it", "a", "an", "his", "her", "their", "there"}
)


_STATEMENT_VERBS = frozenset({"is", "are", "was", "were", "s", "costs", "cost", "means", "includes", "has", "have"})


_SINGLE_WORDS = frozenset(
    {
        # live data
        "today", "tonight", "currently", "outage", "queue",
        # memory of this call
        "remember", "earlier",
        # dialogue and complaints
        "pardon", "louder", "slower", "slowly", "ridiculous", "frustrated", "frustrating",
        "angry", "upset", "worst", "terrible", "unacceptable", "disappointed",
        # steering
        "pretend", "ignore", "roleplay",
        # a crisis
        "suicide", "suicidal", "overdose", "overdosed", "unconscious", "collapsed",
        "bleeding", "choking", "fainted", "swallowed", "seizure", "drowning", "poisoned", "ambulance",
        # abuse
        "stupid", "idiot", "useless", "dumb", "shit", "damn", "hell", "crap", "fuck",
        "fucking", "bullshit", "bloody",
        # identity checks, and names given for anyone
        "otp", "cvv", "named", "surname", "mr", "mrs", "ms", "mister",
        # Hinglish possessives and first person
        "mera", "meri", "mere", "maine", "mujhe", "hamara", "hamari",
        # handing over to a person, Hinglish "I am"
        "supervisor", "hoon", "hun",
    }
)


# Advice that depends on the caller's own situation once they are in the turn:
# "can i take this medicine", not "what does a lawyer charge".
_SENSITIVE = frozenset(
    {
        "pregnancy", "pregnant", "breastfeeding", "allergic", "allergy", "allergies",
        "medicine", "medication", "dosage", "doctor", "symptoms", "sue", "lawsuit",
        "lawyer", "legal", "invest", "investment",
    }
)


# A crisis, said in words: private, and what follows it stays with it.
_CRISIS_PHRASES = (
    ("end", "it", "all"), ("kill", "myself"), ("hurt", "myself"), ("harm", "myself"),
    ("want", "to", "die"), ("self", "harm"), ("end", "my", "life"), ("take", "my", "life"),
    ("reason", "to", "live"), ("better", "off", "dead"), ("not", "breathing"), ("heart", "attack"),
    ("ending", "my", "life"), ("ending", "it", "all"), ("end", "myself"), ("kill", "me"),
    ("panic", "attack"), ("wanna", "die"),
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


_PHRASES = (
    # self-introduction, or anyone's name
    ("my", "name"), ("name", "s"), ("call", "me"), ("i", "m", "called"), ("name", "is"),
    ("name", "was"), ("names", "are"), ("is", "called"), ("was", "called"),
    # memory of this call
    ("did", "i"), ("i", "told", "you"), ("as", "i", "said"), ("i", "mentioned"), ("who", "i", "am"),
    ("have", "i"), ("i", "asked"), ("you", "said"), ("you", "told"), ("you", "mentioned"),
    ("we", "discussed"), ("we", "talked"), ("this", "call"), ("did", "you"), ("did", "we"),
    ("repeat", "the"), ("repeat", "what"), ("repeat", "your"), ("last", "answer"), ("last", "question"),
    ("first", "question"), ("say", "it", "again"),
    # agreeing to what the agent offered
    ("sounds", "good"), ("sounds", "great"), ("sounds", "fine"), ("let", "s", "do"), ("let", "s", "go"),
    ("lock", "it"), ("go", "ahead"), ("works", "for"),
    # personalised advice or prices
    ("should", "i", "order"), ("should", "i", "buy"), ("should", "i", "get"), ("should", "i", "choose"),
    ("should", "i", "pick"), ("best", "for", "me"), ("good", "for", "me"), ("right", "for", "me"),
    ("suitable", "for", "me"), ("recommend", "for", "me"), ("recommend", "me"), ("will", "i", "pay"),
    ("would", "i", "pay"), ("do", "i", "owe"),
    # live data
    ("in", "stock"), ("out", "of", "stock"), ("right", "now"), ("at", "the", "moment"), ("still", "on"),
    ("open", "now"), ("available", "now"), ("working", "now"), ("down", "now"),
    ("app", "down"), ("site", "down"), ("website", "down"), ("server", "down"), ("system", "down"),
    ("app", "working"), ("site", "working"), ("website", "working"), ("the", "wait"), ("wait", "time"),
    # dialogue
    ("i", "meant"), ("say", "that", "again"), ("repeat", "that"), ("come", "again"), ("slow", "down"),
    ("speak", "in"), ("talk", "in"), ("in", "hindi"), ("in", "english"), ("third", "time"),
    ("nobody", "is", "helping"), ("no", "one", "is", "helping"), ("not", "helping"), ("fed", "up"),
    # steering
    ("from", "now", "on"), ("act", "as"), ("you", "are", "now"), ("role", "play"), ("always", "say"),
    ("forget", "everything"), ("forget", "what"), ("forget", "your"), ("forget", "all"),
    ("for", "the", "rest"), ("tell", "everyone"), ("your", "rules"),
    ("your", "instructions"), ("previous", "instructions"), ("system", "prompt"),
    # sensitive advice
    ("safe", "during"), ("safe", "for", "kids"),
    *_CRISIS_PHRASES,
    ("sounds", "right"), ("uh", "huh"), ("that", "s", "it"),
    # Indian-English and Hinglish introductions, personal fit, hand-over, steering
    ("this", "side"), ("bol", "raha"), ("bol", "rahi"), ("name", "you", "have"), ("have", "for", "me"), ("suit", "me"), ("suits", "me"), ("me", "best"), ("put", "me", "through"), ("transfer", "me"), ("connect", "me"), ("from", "here", "on"), ("call", "yourself"),
)


_PHRASES_BY_FIRST = _first_words(_PHRASES)


# Things the caller did or went through. With a how-to after them the turn may be
# answered from the cache, but what they said is never stored.
_STORY_PHRASES = (
    ("i", "ordered"), ("i", "bought"), ("i", "paid"), ("i", "placed"), ("i", "received"),
    ("i", "purchased"), ("i", "returned"), ("i", "booked"), ("i", "cancelled"), ("i", "canceled"),
    ("i", "was", "charged"), ("i", "got", "charged"), ("i", "haven", "t"), ("i", "didn", "t"),
    ("charged", "twice"), ("double", "charged"), ("i", "can", "t"), ("we", "can", "t"),
    ("i", "cannot"), ("we", "cannot"), ("i", "couldn", "t"), ("i", "am", "not", "able"),
    ("i", "m", "not", "able"),
)


_STORY_PHRASES_BY_FIRST = _first_words(_STORY_PHRASES)


_PAST_TENSE = frozenset(
    {
        "lost", "got", "had", "was", "were", "broke", "fell", "left", "went", "came", "took",
        "made", "saw", "gave", "found", "sent", "paid", "bought", "forgot", "spent", "became",
        "hurt", "felt", "heard", "met", "ran", "told", "sold", "wrote", "drove", "flew", "won",
        "lent", "stole", "ate", "drank", "kept", "slept", "woke", "been",
    }
)


# Past forms that ask rather than tell: "i wanted to know", "i was wondering".
_NOT_A_STORY = frozenset({"wanted", "wondered", "hoped", "needed", "liked", "loved", "wished", "preferred"})


_STORY_FILLERS = frozenset({"just", "recently", "already", "also", "never", "have", "ve"})


_DIGITS = re.compile(r"[0-9]{5,}")


# Digits read out in groups: "4 4 0 9", "98 765 43". Commas and points are left
# out, so a price ("1,499") or a weight ("1.5") is not an identifier.
_SPACED_DIGITS = re.compile(r"[0-9]+(?:[ \t-]+[0-9]+)+")


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]@[A-Za-z0-9-]")


# An IPv4 address: personal data, as an IPv6 address already counts (its digit runs).
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"


_IPV4 = re.compile(r"(?<![0-9.])" + _OCTET + r"(?:\." + _OCTET + r"){3}(?![0-9]|\.[0-9])")


_CLAUSES = re.compile(r"([,.!?;:]+)")


# A turn longer than this is private without being read: every rule is linear in
# its length, and a caller's monologue is not a question other callers ask.
_MAX_TURN_CHARS = 1000


# A caller's own health, legal trouble, abuse or money trouble. Told in the first
# person ("i'm pregnant", "my lawyer", "i have hiv"), a how-to after it does not
# make the turn general.
_MATTERS = frozenset(
    {
        # health
        "pregnant", "pregnancy", "breastfeeding", "allergic", "allergy", "allergies", "medicine",
        "medicines", "medication", "medications", "dosage", "dose", "doses", "doctor", "doctors",
        "symptoms", "symptom", "prescribed", "prescription", "diagnosed", "diagnosis", "hiv",
        "cancer", "tumour", "tumor", "diabetes", "diabetic", "asthma", "depression", "depressed",
        "anxiety", "surgery", "therapy", "chemotherapy", "chemo", "pill", "pills", "mg", "insulin",
        "disease", "illness", "sick", "infection", "injury", "injured", "pain", "nausea", "fever",
        "disability", "disabled", "psychiatrist", "therapist", "hospital", "stroke", "seizures",
        "epilepsy", "hepatitis", "miscarriage", "abortion", "rehab", "addiction", "addicted",
        "covid", "dementia", "alzheimer", "alzheimers", "wheelchair", "dialysis", "panic", "blind",
        "deaf", "apnea", "cpap", "pregnent", "pregant", "alergic", "alergy",
        # legal
        "lawyer", "lawyers", "attorney", "sue", "suing", "sued", "lawsuit", "court", "arrested",
        "arrest", "custody", "divorce", "convicted", "criminal", "bail", "jail", "prison", "deported",
        "police", "legal", "dui",
        # abuse
        "hit", "hits", "hitting", "beat", "beats", "beating", "abuse", "abused", "abusive", "assault",
        "assaulted", "raped", "threatens", "threatened", "violent", "violence", "stalking", "stalked",
        "harassed", "harassment", "bullied", "bullying",
        # money trouble and loss
        "debt", "debts", "owe", "bankrupt", "bankruptcy", "evicted", "eviction", "foreclosure",
        "unemployed", "fired", "afford", "overdue", "arrears", "homeless", "died", "death",
        "funeral", "deceased", "widowed", "widow", "passed",
    }
)


_DISCLOSURE_LEADS = (
    ("i", "m"), ("i", "am"), ("i", "have"), ("i", "ve"), ("i", "took"), ("i", "take"), ("i", "was"),
    ("i", "had"), ("i", "got"), ("i", "owe"), ("like", "me"), ("for", "me"),
)


_DISCLOSURE_LEADS_BY_FIRST = _first_words(_DISCLOSURE_LEADS)


# A state of the caller's own that changes the answer ("im pregnant, can i fly", "i want
# to invest my savings, how do i start"): with ANY first-person word, private whatever
# the framing, and so is a turn that opens with one ("pregnant at 30 weeks, can i fly").
# Professions ("what should i do if a doctor is late") and words with an everyday sense
# ("can i book a tennis court") are left to the disclosure rule.
_STATES = (_MATTERS | {"invest", "investment", "investing"}) - {
    "doctor", "doctors", "lawyer", "lawyers", "attorney", "legal", "police", "court", "hospital",
    "therapist", "psychiatrist", "hit", "hits", "hitting", "beat", "beats", "beating", "passed",
    "afford",
}


_SELF_MARKERS = frozenset(
    {"i", "im", "iam", "ive", "me", "my", "mine", "myself", "mi", "mai", "we", "us", "our", "ours"}
)


# "Pregnant women, is coffee safe?" asks about a kind of person, not the caller.
_KINDS_OF_PEOPLE = frozenset(
    {
        "women", "woman", "people", "person", "persons", "mothers", "mums", "moms", "ladies",
        "patients", "travellers", "travelers", "passengers", "customers", "guests", "kids",
        "children", "folks",
    }
)


# Other people the caller speaks for: "for my wife", "my son was arrested".
_RELATIONS = frozenset(
    {
        "husband", "wife", "partner", "son", "daughter", "child", "children", "kid", "kids", "baby",
        "mother", "mom", "mum", "father", "dad", "brother", "sister", "parent", "parents",
        "boyfriend", "girlfriend", "fiance", "fiancee", "grandmother", "grandfather", "grandma",
        "grandpa", "uncle", "aunt", "nephew", "niece", "cousin", "family", "friend", "neighbour",
        "neighbor", "bhai", "didi", "behen",
    }
)


_THIRD_PERSON = frozenset({"he", "she", "him", "her", "his", "hers", "their", "theirs"})


# One named person the caller speaks about ("wife has diabetes", "she is pregnant"),
# not a kind of person ("a family lawyer").
_SOMEONE = (_RELATIONS | _THIRD_PERSON) - {
    "family", "friend", "partner", "children", "kids", "kid", "child", "parent", "parents", "baby",
    "neighbour", "neighbor", "cousin", "their", "theirs",
}


# A follow-up this short, after an emergency or a medical turn, is about it.
_FOLLOW_UP_WORDS = 8


_URGENT = _MATTERS | frozenset(
    {
        "suicide", "suicidal", "overdose", "overdosed", "unconscious", "collapsed", "bleeding",
        "choking", "fainted", "swallowed", "seizure", "drowning", "poisoned", "ambulance",
        "breathing", "fire", "emergency", "cpr",
    }
)


# Numbers that identify someone.
_ID_WORDS = frozenset(
    {
        "pin", "code", "otp", "order", "account", "card", "member", "membership", "policy",
        "ticket", "reference", "ref", "booking", "number", "id", "password", "passcode", "cvv",
        "pnr", "tracking", "invoice", "customer", "phone", "mobile", "ssn", "pan", "aadhaar",
        "passport", "licence", "license", "serial", "claim", "case", "transaction", "receipt",
        "born", "birth", "dob", "birthday", "postcode", "zip", "pincode", "iban", "ord", "flight",
        "seat", "room", "awb", "consignment", "docket", "nasci", "naci", "nací", "nacido", "nacida",
        "nascido", "nascida", "né", "née", "paida", "janam",
    }
)


_NUMBER_WORDS = _SPOKEN_DIGITS | _DIGIT_REPEATS | frozenset(
    {
        "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen",
        "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty",
        "ninety", "hundred", "thousand", "lakh", "lakhs", "crore", "million",
    }
)


# Amounts said about oneself ("i owe forty thousand"), not small counts ("can i get two").
_AMOUNT_WORDS = _NUMBER_WORDS - _SPOKEN_DIGITS - _DIGIT_REPEATS


_MONTHS = frozenset(
    {
        "january", "february", "march", "april", "may", "june", "july", "august", "september",
        "october", "november", "december", "jan", "feb", "apr", "jun", "jul", "aug", "sep",
        "sept", "oct", "nov", "dec",
    }
)


_ORDINALS = frozenset(
    {
        "first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth",
        "tenth", "eleventh", "twelfth", "thirteenth", "fourteenth", "fifteenth", "sixteenth",
        "seventeenth", "eighteenth", "nineteenth", "twentieth", "thirtieth",
    }
)


_DATE = re.compile(r"(?<![0-9])[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}(?![0-9])")


_STREET_WORDS = frozenset(
    {
        "street", "st", "road", "rd", "lane", "ln", "avenue", "ave", "drive", "boulevard", "blvd",
        "marg", "nagar", "colony", "sector", "apartments", "tower", "towers", "block", "society",
        "crescent", "terrace", "court", "place", "square", "highway", "calle", "rua", "rue",
        "avenida", "strasse", "straße", "plaza", "platz",
    }
)


# Codes and numbers that identify on their own: "#7741", "AB-7741", "b-204", "AI302",
# "is 4409 right" (not a year, a price, or an amount of something).
_HASH_NUMBER = re.compile(r"#\s*[0-9]{3,}")


_CODE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]{1,4}-?[0-9]{3,}(?![A-Za-z0-9])")


_QUANTITIES = (
    "rupees|rs|inr|dollars|usd|euros|eur|pounds|gbp|units|items|pieces|people|guests|users|mb|gb|tb|kb|"
    "mah|km|kg|g|ml|calories|steps|words|pages|points|miles|sq|square|feet|ft|sqft|watts|w|rpm|hours|"
    "minutes|seconds|days|years|plan|model|series|edition|k|mp"
)


_BARE_NUMBER = re.compile(
    r"(?<![0-9.,$€£₹])(?<![$€£₹]\s)(?!(?:19|20)[0-9]{2}(?![0-9]))[0-9]{4,}(?![0-9.,])"
    r"(?!\s*(?:" + _QUANTITIES + r")\b)",
    re.IGNORECASE,
)


_ENDS_IN = (("ends", "in"), ("ends", "with"), ("ending", "in"), ("ending", "with"), ("end", "in"))


_ENDS_IN_BY_FIRST = _first_words(_ENDS_IN)


_UNIT_WORDS = frozenset({"flat", "apartment", "apt", "house", "unit", "plot", "suite", "door", "sector", "block"})


_FIRST_PERSON_SUBJECTS = frozenset({"i", "we"})


def _has_digit(word: str) -> bool:
    return any(c.isdecimal() for c in word)  # any script's digits: "４４０９", "٤٤٠٩"


def _amount(word: str) -> bool:
    return sum(c.isdecimal() for c in word) >= 2 or word in _AMOUNT_WORDS


def _identifies(text: str, words: List[str]) -> bool:
    """A number, date, email, spelling or address that can identify someone."""
    ids = any(w in _ID_WORDS for w in words)
    # "is 4409 the right pin", "where is order 742"
    if ids and any(len(w) >= 3 and _has_digit(w) for w in words):
        return True
    for index, word in enumerate(words):
        # "i'm 45", "i owe 40000", "my pin is 4409"
        reach = 2 if word in _FIRST_PERSON_SUBJECTS else 3 if word in _POSSESSIVES else 0
        if any(_amount(w) for w in words[index + 1:index + 1 + reach]):
            return True
        # "42 park lane", "flat 12"
        if _has_digit(word) and any(w in _STREET_WORDS for w in words[index + 1:index + 5]):
            return True
        if word in _UNIT_WORDS and any(_has_digit(w) for w in words[index + 1:index + 3]):
            return True
        # "priya sharma at gmail", "send it to priya at hotmail"
        if word == "at" and index + 1 < len(words) and words[index + 1].endswith("mail"):
            return True
    if _HASH_NUMBER.search(text) or _CODE.search(text) or _BARE_NUMBER.search(text):
        return True
    for index, word in enumerate(words):
        # "card number ends with four four", "ends in 09"
        if _has_phrase(words[index:index + 2], _ENDS_IN_BY_FIRST) and any(
            _has_digit(w) or w in _NUMBER_WORDS for w in words[index + 2:index + 4]
        ):
            return True
        # "house number twelve", "calle mayor 10"
        if word in _UNIT_WORDS and any(w in _NUMBER_WORDS for w in words[index + 1:index + 4]):
            return True
        if word in _STREET_WORDS and any(_has_digit(w) for w in words[index + 1:index + 4]):
            return True
    tied = ids or any(w in _FIRST_PERSON for w in words)
    if tied and _DATE.search(text):
        return True
    if tied and any(
        w in _MONTHS and any(_has_digit(n) or n in _NUMBER_WORDS or n in _ORDINALS for n in words[max(0, i - 2):i + 3])
        for i, w in enumerate(words)
    ):
        return True
    if "at" in words and ("email" in words or "mail" in words):
        return True
    # Letters spelled out: "j o h n", "x j 4 k q".
    run = 0
    for token in text.split():
        token = token.strip(_TRIM)
        run = run + 1 if len(token) == 1 and token.isalnum() else 0
        if run >= 3:
            return True
    return False


# Words that start a name when said alone in a clause: "i'm priya", "soy carlos".
_INTRO_LEADS = (
    ("i", "am"), ("i", "m"), ("this", "is"), ("it", "s"), ("it", "is"), ("soy",), ("je", "suis"),
    ("ich", "bin"), ("eu", "sou"), ("sono",), ("ik", "ben"), ("aqui", "é"), ("aqui", "e"), ("sou",),
    ("habla",), ("fala",), ("ici",),
)


# Phrases a name always follows, in the languages callers use.
_INTRODUCTIONS = (
    ("mi", "nombre"), ("me", "llamo"), ("je", "m", "appelle"), ("mon", "nom"), ("mein", "name"),
    ("ich", "heisse"), ("ich", "heiße"), ("meu", "nome"), ("me", "chamo"), ("mi", "chiamo"),
    ("mijn", "naam"), ("mera", "naam"), ("meri", "naam"), ("naam", "hai"), ("myname",),
    ("you", "re", "speaking", "with"), ("you", "are", "speaking", "with"), ("you", "re", "talking", "to"),
    ("you", "are", "talking", "to"), ("ke", "naam"), ("ka", "naam"), ("ki", "naam"), ("naam", "pe"),
    ("naam", "par"), ("naam", "se"),
)


_INTRODUCTIONS_BY_FIRST = _first_words(_INTRODUCTIONS)


_NAME_ARTICLES = frozenset({"o", "a", "el", "la", "le"})


_CLAUSE_OPENERS = _DISCOURSE | _GREETINGS | {"hola", "bonjour", "salut", "hallo", "ola", "olá", "ciao", "um", "uh", "well"}


# Before a capitalised word, these make it a person: "for Rahul", "Dr Mehta",
# "does Mohit have".
_NAME_SLOTS = frozenset({"for", "dr", "prof", "sir", "madam", "miss", "shri", "smt"})


_TITLES = _NAME_SLOTS - {"for"}


_AUXILIARIES = frozenset({"can", "could", "does", "did", "is", "has", "had", "will", "would", "should", "may", "was"})


# What a person, not a product, does after an opening auxiliary: "does Mohit have".
_PERSON_VERBS = frozenset(
    {
        "have", "has", "had", "need", "want", "pick", "get", "come", "coming", "call", "called",
        "know", "live", "book", "booked", "order", "ordered", "pay", "paid", "arrive", "arrived",
        "still", "already", "sign", "signed", "speak", "talk", "collect", "collects", "visit", "attend",
    }
)


# After a name, what a person does: "Priya called", "Arjun Mehta checked in".
_NAME_VERBS = frozenset(
    {
        "has", "have", "had", "called", "calls", "said", "says", "told", "wants", "needs", "checked",
        "booked", "ordered", "paid", "sent", "asked", "pick", "picks", "collect", "collects", "come",
        "comes", "coming", "get", "gets", "speak", "talk",
    }
)


# After a name in Hinglish, these make it a place, a festival or a thing: "Durga Puja
# mein", "Patna ka". "<name> ka order" is a person's, found in lower case below.
_POSTPOSITIONS = frozenset({"mein", "me", "pe", "par", "ka", "ki", "ke", "se", "wala", "wale", "wali", "main", "tak"})


_PLACE_PREPOSITIONS = frozenset(
    {"to", "in", "at", "from", "near", "into", "via", "across", "around", "within", "on", "en", "em", "au", "aux"}
)


# A name only matters next to a person's own business or a person's action: "is the
# order for Rahul ready", "Dr. Iyer told me to call you". "Do you ship to Hong Kong",
# "what's the McDonald's breakfast time" name places and brands.
_PERSONAL_MATTERS = frozenset(
    {
        "account", "accounts", "order", "orders", "booking", "bookings", "appointment", "appointments",
        "parcel", "parcels", "package", "delivery", "refund", "refunds", "bill", "bills", "invoice",
        "ticket", "tickets", "prescription", "reservation", "reservations", "subscription",
        "payment", "balance", "card", "loan", "claim", "statement", "shipment", "table", "room",
    }
)


_PERSON_CUES = frozenset(
    {
        "call", "called", "calling", "tell", "told", "said", "says", "ask", "asked", "speak",
        "speaking", "talk", "available", "pick", "collect", "wants", "needs", "coming", "arrived",
        "booked", "ordered", "paid", "sent", "holder", "here", "birthday", "checked",
    }
)


# "Can I speak to Meera", "pls connect to raghav sir": a person asked for by name.
_ASK_FOR = (
    ("speak", "to"), ("speak", "with"), ("talk", "to"), ("talk", "with"), ("connect", "to"),
    ("connect", "me", "to"), ("transfer", "to"), ("transfer", "me", "to"), ("ask", "for"),
    ("put", "me", "through", "to"),
)


_ASK_FOR_BY_FIRST = _first_words(_ASK_FOR)


_ROLES = frozenset(
    {
        "someone", "somebody", "anyone", "anybody", "agent", "human", "person", "manager",
        "representative", "operator", "sales", "billing", "accounts", "department", "reception",
        "front", "staff", "engineer", "technician", "executive", "advisor", "adviser", "officer",
    }
)


_POSSESSIVE_NAME = re.compile(r"([^\W\d_]+)['’]s\s+([^\W\d_]+)")


# Capitalised words that are not names: days, months, holidays, plan tiers and the
# common nouns of product names ("Apple Pay", "Google Maps").
_COMMON_CAPITALS = frozenset(
    {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "mondays",
        "tuesdays", "wednesdays", "thursdays", "fridays", "saturdays", "sundays", "christmas",
        "easter", "diwali", "eid", "holi", "thanksgiving", "new", "year", "years", "eve", "black",
        "cyber", "basic", "standard", "pro", "plus", "max", "mini", "lite", "ultra", "free",
        "starter", "maps", "map", "store", "app", "apps", "cloud", "music", "tv", "wallet", "bank",
        "mail", "watch", "pad", "book", "air", "home", "assistant", "plan", "plans", "support",
        "service", "services", "care", "team", "help", "desk", "center", "centre", "express",
        "airport", "station", "mall", "market", "city", "park", "international", "airlines",
        "insurance", "life", "health", "energy", "fiber", "fibre", "broadband", "internet",
        "wifi", "english", "hindi", "spanish", "french", "german", "terms", "conditions",
        "privacy", "policy", "hello", "hi", "thanks", "thank", "please", "okay", "sorry", "wi", "fi",
        "office", "checkout", "eats",
    }
)


_KNOWN_WORDS = frozenset().union(
    _COMMON_CAPITALS, _FUNCTION_WORDS, _ACTION_VERBS, _CALLER_KINDS, _OWNED_THINGS, _STATE_WORDS,
    _MATTERS, _RELATIONS, _ID_WORDS, _NUMBER_WORDS, _MONTHS, _ORDINALS, _STREET_WORDS, _UNIT_WORDS,
    _GREETINGS, _DISCOURSE, _REPLY_LEADS, _SOFT_REPLY_LEADS, _QUESTION_LEADS, _WH_WORDS, _SINGLE_WORDS,
    _SENSITIVE, _BARE, _NON_REFERENTS, _PRONOUN_FOLLOWERS, _CLAUSE_MARKERS, _REQUEST_VERBS,
    _STATEMENT_SUBJECTS, _OWNERS - _OTHER_POSSESSIVES, _FIRST_PERSON, _AUXILIARIES,
)


def _unknown(word: str) -> bool:
    """Not a word these rules know, nor shaped like a verb or an adjective: maybe a name."""
    return word not in _KNOWN_WORDS and word not in _ROLES and not word.endswith(("ing", "ed", "ly"))


def _names_someone(text: str, words: List[str]) -> bool:
    """A name, given by the caller or about anyone, in an introduction or as a proper noun."""
    if _has_phrase(words, _INTRODUCTIONS_BY_FIRST):
        return True
    personal = any(w in _PERSONAL_MATTERS or w in _PERSON_CUES for w in words)
    for index in range(len(words)):
        for phrase in _ASK_FOR_BY_FIRST.get(words[index], ()):
            end = index + len(phrase)
            if tuple(words[index:end]) == phrase and end < len(words) and _unknown(words[end]):
                return True
    # "is sanjay's order ready", in any case
    for match in _POSSESSIVE_NAME.finditer(text):
        if _unknown(match.group(1).lower()) and match.group(2).lower() in _PERSONAL_MATTERS:
            return True
    # "rahul ka order", "priya ki booking"
    for index in range(1, len(words) - 1):
        if words[index] in ("ka", "ki", "ke") and words[index + 1] in _PERSONAL_MATTERS and _unknown(words[index - 1]) \
                and words[index - 1] not in _FUNCTION_WORDS:
            return True
    for clause in _CLAUSES.split(text)[0::2]:
        said = _words(clause)
        while said and said[0] in _CLAUSE_OPENERS:
            said = said[1:]
        # "priya here", "priya speaking"
        if 2 <= len(said) <= 3 and said[-1] in ("here", "speaking") and not (
            said[0] in _WH_WORDS or said[0] in _QUESTION_LEADS or said[0] in _FUNCTION_WORDS
        ):
            return True
        for lead in _INTRO_LEADS:
            rest = said[len(lead):]
            while lead[0] not in ("i", "this", "it") and rest[:1] and rest[0] in _NAME_ARTICLES:  # "sou a mariana"
                rest = rest[1:]
            if tuple(said[:len(lead)]) != lead or not rest:
                continue
            if len(rest) <= 3 and not any(w in _FUNCTION_WORDS or w in _WH_WORDS for w in rest):
                return True
            if _unknown(rest[0]) and rest[0] not in _FUNCTION_WORDS:  # "i'm vikram and i want ..."
                return True
        # "can priya pick up the order", "will priya get the refund", in any case
        if (
            len(said) > 2 and said[0] in _AUXILIARIES and _unknown(said[1]) and said[2] in _PERSON_VERBS
            and personal
        ):
            return True
    return _capitalised_name(text, words)


def _capitalised(word: str) -> bool:
    return word[0].isupper() and not word.isupper()


def _capitalised_name(text: str, words: List[str]) -> bool:
    """A capitalised name (one word, or two in a row) in a person's place: after a title
    ("Dr. Iyer"), before what a person does ("Priya called", "does Mohit have an
    appointment"), or after one of the caller's own matters ("the order for Rahul").
    Followed by a Hinglish postposition it is a place or a festival ("Durga Puja mein")."""
    tokens = list(_TOKEN.finditer(text))
    if len(tokens) != len(words):
        return False  # ponytail: tokenisation disagrees (exotic case folding); other rules still apply
    first_matter = next((i for i, w in enumerate(words) if w in _PERSONAL_MATTERS), len(words))
    personal = first_matter < len(words) or any(w in _PERSON_CUES for w in words)
    for index, match in enumerate(tokens):
        word = match.group()
        if not _capitalised(word) or words[index] in _KNOWN_WORDS:
            continue
        lead = words[index - 1] if index > 0 else ""
        if lead in _TITLES:
            return True  # a title, with or without its period: "Dr. Iyer"
        end = index + 1
        if end < len(tokens) and text[match.end():tokens[end].start()].isspace() and _capitalised(tokens[end].group()):
            if words[end] in _KNOWN_WORDS:
                continue  # "Apple Pay", "Google Maps"
            end += 1
        after = words[end] if end < len(words) else ""
        if after in _POSTPOSITIONS:
            continue
        if after in _NAME_VERBS and personal:
            return True
        if first_matter < index and lead not in _PLACE_PREPOSITIONS:
            return True
    return False


def _discloses(words: List[str]) -> bool:
    """The caller's own health, legal, abuse or money matter, told in the first person,
    or someone's they speak about."""
    return any(w in _MATTERS for w in words) and (
        any(w in _POSSESSIVES or w in _SOMEONE for w in words)
        or _has_phrase(words, _DISCLOSURE_LEADS_BY_FIRST)
    )


def _carries_detail(text: str, words: List[str]) -> bool:
    """Something of the caller's in a story: who else, a number, a name, a matter. The
    caller's own things ("i forgot my password") stay as general as "how do i reset my password"."""
    return (
        any(w in _MATTERS or w in _RELATIONS or w in _THIRD_PERSON for w in words)
        or any(_has_digit(w) for w in words)
        or bool(_proper_nouns(text))
    )


def _unreadable(text: str) -> bool:
    """Letters these rules cannot read: anything outside the Latin script. A
    turn the rules cannot read cannot be shown to be safe to share."""
    return any(
        ch.isalpha() and not ("a" <= ch <= "z" or "A" <= ch <= "Z" or "À" <= ch <= "ɏ" or "Ḁ" <= ch <= "ỿ")
        for ch in text
    )


def _reads_out_digits(text: str, words: List[str]) -> bool:
    if any(sum(c.isdigit() for c in group) >= 4 for group in _SPACED_DIGITS.findall(text)):
        return True
    run = 0
    for word in words:
        # "seven four two", "forty four oh nine", "double four zero nine"
        spoken = word in _NUMBER_WORDS or (len(word) == 1 and "0" <= word <= "9")
        run = run + 1 if spoken else 0
        if run >= 3:
            return True
    return False


def _commands(text: str) -> bool:
    """A clause that opens with a verb acting on something: "set a timer", "fine, book it"."""
    parts = _CLAUSES.split(text)
    for clause, end in zip(parts[0::2], parts[1::2] + [""]):
        if "?" in end:
            continue
        words = _words(clause)
        while words and words[0] in _DISCOURSE:
            words = words[1:]
        if len(words) > 1 and words[0] in _ACTION_VERBS and words[1] in _ACTION_OBJECTS and not any(
            w in _WH_WORDS for w in words
        ):
            return True
    return False


def _asserts(text: str, words: List[str]) -> bool:
    rest = [w for w in words if w not in _GREETINGS]
    while rest and (rest[0] in _SOFT_REPLY_LEADS or rest[0] in _CONNECTIVES):
        rest = rest[1:]
    return (
        bool(rest) and rest[0] in _STATEMENT_SUBJECTS and "?" not in text
        and not any(w in _WH_WORDS for w in rest) and any(w in _STATEMENT_VERBS for w in rest)
    )


def _tells_own_story(words: List[str]) -> bool:
    if _has_phrase(words, _STORY_PHRASES_BY_FIRST):
        return True
    for index, word in enumerate(words[:-1]):
        if word not in ("i", "we"):
            continue
        at = index + 1
        while at < len(words) - 1 and words[at] in _STORY_FILLERS:
            at += 1
        verb = words[at]
        after = words[at + 1] if at + 1 < len(words) else ""
        if verb in ("was", "were") and after.endswith("ing"):
            continue
        regular = verb.endswith("ed") and not verb.endswith("eed")  # "ordered", not "need"
        if verb in _PAST_TENSE or (len(verb) > 3 and regular and verb not in _NOT_A_STORY):
            return True
    return False


def _never_share(text: str, words: List[str]) -> bool:
    """Whether a turn's answer must never be shared, whatever the rest of the rules say."""
    if _unreadable(text):
        return True
    if _DIGITS.search(text) or _EMAIL.search(text) or _IPV4.search(text) or _reads_out_digits(text, words):
        return True
    if "at" in words and "dot" in words and any(w in _EMAIL_ENDINGS for w in words):
        return True
    if any(w in _SINGLE_WORDS for w in words) or _has_phrase(words, _PHRASES_BY_FIRST):
        return True
    if _identifies(text, words) or _names_someone(text, words):
        return True
    if words and words[0] in _GREETINGS:
        rest = [w for w in words if w not in _GREETINGS]
        if any(tuple(rest[:len(p)]) == p for p in _INTRO_AFTER_GREETING):
            return True
    if 1 < len(words) <= 5 and words[-1] in ("here", "speaking"):
        return True
    if words and words[0] == "myself":  # "Myself Anjali, I need help."
        return True
    for index, word in enumerate(words):
        if word not in _POSSESSIVES:
            continue
        for at in (index + 1, index + 2):  # "my phone", "my washing machine"
            if at < len(words) and words[at] in _OWNED_THINGS and any(w in _STATE_WORDS for w in words[at + 1:at + 5]):
                return True
    if _commands(text):
        return True
    for index, word in enumerate(words):
        for lead in _ACTION_LEADS_BY_FIRST.get(word, ()):
            end = index + len(lead)
            if tuple(words[index:end]) == lead and end < len(words) and words[end] in _ACTION_VERBS:
                return True
    if words and not any(w in _WH_WORDS for w in words):
        if words[0] in _REPLY_LEADS:
            return True
        if words[0] in _SOFT_REPLY_LEADS:
            rest = words[1:]
            while rest and (rest[0] in _SOFT_REPLY_LEADS or rest[0] in _CONNECTIVES):
                rest = rest[1:]
            if not rest or rest[0] not in _QUESTION_LEADS:
                return True
    if _asserts(text, words):
        return True
    for index in range(len(words) - 2):
        # "how many points do i have", not "do i have to pay for returns"
        if tuple(words[index:index + 3]) == ("do", "i", "have") and (index + 3 >= len(words) or words[index + 3] != "to"):
            return True
    return False


# "i have lupus", "tengo lupus", "j'ai la sclérose", "i was diagnosed with ...": the
# shape of a diagnosis, so the condition need not be in any list.
_DIAGNOSIS_LEADS = (
    ("i", "have"), ("i", "ve", "got"), ("i", "got"), ("tengo",), ("tenho",), ("j", "ai"),
    ("diagnosed",), ("suffering", "from"), ("suffer", "from"), ("sufro", "de"), ("sofro", "de"),
    ("souffre", "de"), ("padezco",), ("mujhko",),
)


_DIAGNOSIS_LEADS_BY_FIRST = _first_words(_DIAGNOSIS_LEADS)


_ARTICLES = frozenset({"a", "an", "un", "una", "uma", "um", "une", "la", "le", "el", "de", "with"})


# What a caller "has" that is not a condition: "i have a question", "tengo una duda".
_HAVE_OBJECTS = frozenset(
    {
        "question", "questions", "query", "queries", "doubt", "doubts", "issue", "issues", "problem",
        "problems", "concern", "concerns", "complaint", "feedback", "suggestion", "idea", "time",
        "money", "cash", "access", "permission", "enough", "nothing", "something", "everything",
        "some", "already", "just", "also", "still", "been", "got", "pregunta", "preguntas", "duda",
        "dudas", "problema", "pergunta", "perguntas", "dúvida", "duvida", "minute", "moment", "second",
        "another", "more", "few", "several", "multiple",
    }
)


def _diagnosis(words: List[str]) -> bool:
    for index, word in enumerate(words):
        for lead in _DIAGNOSIS_LEADS_BY_FIRST.get(word, ()):
            end = index + len(lead)
            if tuple(words[index:end]) != lead:
                continue
            while end < len(words) and words[end] in _ARTICLES:
                end += 1
            if end < len(words) and _unknown(words[end]) and words[end] not in _HAVE_OBJECTS and not any(
                c.isdecimal() for c in words[end]
            ):
                return True
    return False


def _sensitive_self(words: List[str]) -> bool:
    """A sensitive state with any first-person word, or a turn that opens with one."""
    if words and words[0] in _STATES and (len(words) == 1 or words[1] not in _KINDS_OF_PEOPLE):
        return True
    return any(w in _STATES for w in words) and any(w in _SELF_MARKERS for w in words)


_ASKING_WORDS = _WH_WORDS | {"kya", "kab", "kahan", "kaise", "kitna", "kitne", "kaun", "kyun", "kyon"}


_ASKING_LEADS = _QUESTION_LEADS | _CLAUSE_MARKERS | _ACTION_VERBS


_FIRST_CLAUSE = re.compile(r"[,.\-–—]")


# Clauses that say nothing either way: "hi", "okay", "thanks".
_NEUTRAL = _CLAUSE_OPENERS | _SOFT_REPLY_LEADS | _REPLY_LEADS | {"thanks", "thank", "you"}


def _asks(text: str) -> bool:
    """Shaped as a question or a request from its first clause on: "Bipolar, can you
    help?" is not, "Hi, what are your hours?" is. A greeting or acknowledgement first is
    skipped."""
    for clause in _FIRST_CLAUSE.split(text):
        said = _words(clause)
        if not said or all(w in _NEUTRAL for w in said):
            continue
        return (
            "?" in clause or any(w in _ASKING_WORDS for w in said) or said[0] in _ASKING_LEADS
            or _has_phrase(said, _ACTION_LEADS_BY_FIRST) or _procedural(said)
        )
    return False


def _is_personal(text: str) -> bool:
    if len(text or "") > _MAX_TURN_CHARS:
        return True
    words = _words(text)
    if (
        _never_share(text, words) or _describes_caller(words) or _discloses(words) or _sensitive_self(words)
        or _urgent(words) or _diagnosis(words)
    ):
        return True
    owned = _owned_record_at(words)
    story = _tells_own_story(words)
    advice = any(w in _SENSITIVE for w in words) and any(w in _FIRST_PERSON for w in words)
    if owned is None and not story and not advice:
        return False
    if _procedural(words):
        # A how-to after the caller's story may be looked up, unless the story
        # holds something of theirs: then nothing of it leaves the SDK.
        return story and _carries_detail(text, words)
    if story or advice or _requests(words):
        return True
    if owned > 0 and words[owned - 1] in _OWNER_PREPOSITIONS:
        # "i'm calling for my mother": someone else the caller speaks for
        return words[owned + 1] in _RELATIONS or _is_state_interrogative(words)
    return True


def _lookup_only(text: str) -> bool:
    """A how-to after the caller's own story ("i received a damaged product, how do
    i return it"): a shared answer may be served, but nothing of the turn is stored."""
    return not _is_personal(text) and _tells_own_story(_words(text))


def _has_antecedent(before: List[str]) -> bool:
    return any(word not in _FUNCTION_WORDS and word not in _NON_REFERENTS for word in before)


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


def _fill(shape: str, values: Dict[str, str]) -> Optional[str]:
    # One pass: a value that itself contains "{other}" is spoken as-is, never
    # expanded into another slot's value.
    if any(name not in values for name in _SLOT.findall(shape)):
        return None
    return _SLOT.sub(lambda m: values[m.group(1)], shape)


# Shorter values are replaced only as whole words, and one- or two-character
# values not at all: count=2 must not turn "24 hours" into "{count}4 hours".
_MIN_ABSTRACT_LEN = 3


def _abstract(answer: str, values: Dict[str, str]) -> str:
    shaped = answer
    for name, value in sorted(values.items(), key=lambda pair: -len(pair[1] or "")):
        if value and len(value) >= _MIN_ABSTRACT_LEN:
            pattern = r"(?<![\w])" + re.escape(value) + r"(?![\w])"
            shaped = re.sub(pattern, "{" + name + "}", shaped)
    return shaped


def _flatten(text: str) -> str:
    return "".join(_words(text))


def _leaks(shaped: str, values: Dict[str, str]) -> bool:
    flat = _flatten(shaped)
    return any(value and _flatten(value) in flat for value in values.values())


# What the server puts in a stored answer in place of a caller's detail (its PII scrubber):
# "pii_email_k3fa9". Spoken, it is noise at best.
_PII_PLACEHOLDER = re.compile(
    r"(?<![A-Za-z0-9_])pii_(?:email|phone|natid|card|person|location|ip|dob|passport|iban)_[A-Za-z0-9]+",
    re.IGNORECASE,
)


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


# The checks below are for past transcripts only (warm_from_calls). A live turn
# needs none of them: its model reads only what decide() hands it. A past
# answer was written with the whole call in view.
# A caller turn that tries to change what the model says for the rest of the call.
_STEERING = (
    ("pretend",), ("from", "now", "on"), ("for", "this", "call"), ("for", "the", "rest"),
    ("ignore",), ("forget",), ("act", "as"), ("you", "are", "now"), ("assume",),
    ("always", "say"), ("tell", "everyone"), ("roleplay",), ("role", "play"),
)


_STEERING_BY_FIRST = _first_words(_STEERING)


# Phrases after which the caller gives a name: "my name is sarah", "this is raj".
_NAMING = (("name", "is"), ("call", "me"), ("this", "is"), ("i", "m"), ("i", "am"))


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _proper_nouns(text: str) -> set:
    """Words capitalised mid-sentence ("... my agent Priya said"), lower-cased."""
    found = set()
    for match in _TOKEN.finditer(text or ""):
        word, before = match.group(), (text[:match.start()].rstrip() or ".")
        if word[0].isupper() and word != "I" and before[-1] not in ".!?":
            found.add(word.lower())
    return found


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


# Words that make a sentence about one person, not the business.
_PERSON_WORDS = frozenset({
    "caller", "customer", "user", "client", "patient", "member", "guest", "student",
    "name", "named", "account", "acct", "dob", "birthday", "born", "called", "calling",
    "talking", "speaking", "mr", "mrs", "ms", "mx", "miss", "dr", "prof", "he", "she", "him",
    "his", "her", "hers",
})


# A "label: value" line about one person's record or contact ("Phone: 555 0199",
# "Location: Pune"), unless the label says it is the business's own ("Support phone: ...").
_RECORD_LABELS = frozenset({
    "phone", "mobile", "email", "address", "order", "booking", "reservation", "ticket", "case",
    "policy", "plan", "balance", "dob", "id", "city", "location", "company", "employer",
})


# Words that make a sentence about the business even when it names a person word:
# "Our customer service line is 1800 555 0100", "We help our customers with ...".
_BUSINESS_WORDS = frozenset({
    "support", "our", "office", "helpline", "help", "toll", "free", "business", "sales",
    "main", "head", "store", "shop", "branch", "service", "services", "care", "line", "we",
    "us", "customers", "callers", "users", "clients", "patients", "members", "guests",
})


# Sentence ends: . ! ? or ; then space, or a line break; never the dots inside an email
# address or a decimal, nor the one after a title ("Mr. Sharma", "Prof. Rao").
_SENTENCE_END = re.compile(
    r"(?<!\bMr\.)(?<!\bMs\.)(?<!\bMx\.)(?<!\bDr\.)(?<!\bSt\.)(?<!\bSr\.)(?<!\bJr\.)(?<!\bMrs\.)(?<!\bProf\.)"
    r"(?<=[.!?;])\s+|\n+"
)


# Runs of digits that belong together ("555 0199", "1800-555-0100", "99,812") make one number.
_NUMBER_RUN = re.compile(r"[0-9]+(?:[ ,\-./][0-9]+)*")


def _numbers(text: str) -> List[str]:
    return [re.sub(r"[^0-9]", "", run) for run in _NUMBER_RUN.findall(text or "")]


def _is_decimal_word(word: str) -> bool:
    return any(c.isdecimal() for c in word)


_LABEL = re.compile(r"^\s*([^:=\n]{1,40}?)\s*[:=]\s*(.*)$")


_LABEL_WORDS = _RECORD_LABELS | _PERSON_WORDS


def _label(sentence: str) -> tuple:
    """("label", "value") of a "Label: value" or "key=value" sentence, else ("", "")."""
    match = _LABEL.match(sentence)
    return (match.group(1), match.group(2)) if match else ("", "")


def _about_a_person(sentence: str, words: List[str]) -> bool:
    present = set(words)
    if present & _PERSON_WORDS and not present & _BUSINESS_WORDS:
        return True
    label, value = _label(sentence)
    label_words = set(_words(label))
    return bool(value.strip() and label_words & _LABEL_WORDS and not label_words & _BUSINESS_WORDS)


def _value_words(value: str) -> set:
    return {w for w in _words(value) if w not in _FUNCTION_WORDS and w not in _LABEL_WORDS
            and not _is_decimal_word(w) and w not in _EMAIL_ENDINGS}


def _prompt_details(instructions: str) -> tuple:
    """Caller details in one system prompt, read on its own (see above), as
    (words, numbers). In its sentences about a person: the capitalised words (a
    sentence's first only when the next is capitalised too, as in "Asha Rao called"),
    email words, every number, and the whole value of a "Label: value" / "key=value"
    about a person's record. Lines under a heading about a person ("Caller record:"), up
    to a blank line, are all details."""
    words_found: set = set()
    numbers_found: set = set()
    in_block = False
    for line in (instructions or "").split("\n"):
        if not line.strip():
            in_block = False
            continue
        if in_block:
            words_found |= _value_words(line)
            numbers_found.update(n for n in _numbers(line) if n)
            continue
        for sentence in _SENTENCE_END.split(line):
            words = _words(sentence)
            if not words or not _about_a_person(sentence, words):
                continue
            if sentence.rstrip().endswith(":") and not _label(sentence)[1].strip():
                in_block = True  # a heading: what follows is this person's record
            numbers_found.update(n for n in _numbers(sentence) if n)
            label, value = _label(sentence)
            if value.strip() and set(_words(label)) & _LABEL_WORDS:
                words_found |= _value_words(value)
            tokens = [t.group() for t in _TOKEN.finditer(sentence)]
            for index, word in enumerate(tokens):
                low = word.lower()
                if low in _LABEL_WORDS or low in _FUNCTION_WORDS or not word[0].isupper() or _is_decimal_word(word):
                    continue
                if index == 0 and not (index + 1 < len(tokens) and tokens[index + 1][0].isupper()):
                    continue  # "Always greet ...": a sentence's first word, not a name
                words_found.add(low)
            for address in re.findall(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+", sentence):
                words_found |= {w for w in _words(address) if w not in _EMAIL_ENDINGS and not w.isdecimal()}
    return words_found, numbers_found


class _PromptBaseline:
    """What every system prompt an agent was seen with has in common, in this process."""

    __slots__ = ("prompts", "words", "numbers")

    def __init__(self) -> None:
        self.prompts: set = set()  # up to two distinct prompts: enough to know it varies
        self.words: Optional[set] = None
        self.numbers: Optional[set] = None


_BASELINES: "collections.OrderedDict[tuple, _PromptBaseline]" = collections.OrderedDict()


_BASELINES_MAX = 1024


_BASELINES_LOCK = threading.Lock()


def _reset_prompt_baselines() -> None:
    """For tests: forget every agent's prompts."""
    with _BASELINES_LOCK:
        _BASELINES.clear()


def _caller_details(instructions: str, agent_key: Optional[tuple] = None) -> tuple:
    """Caller details in this call's system prompt, as (words, numbers): the sentences
    about a person, and once the agent's prompt has been seen to vary, also whatever
    differs from its other calls. The first two prompts seen can both be one caller's
    (only a date differs), so what is common to them is never taken as not a detail."""
    if agent_key is None:
        return _prompt_details(instructions)
    words = set(_words(instructions))
    numbers = {n for n in _numbers(instructions) if n}
    with _BASELINES_LOCK:
        baseline = _BASELINES.pop(agent_key, None) or _PromptBaseline()
        _BASELINES[agent_key] = baseline  # the most recent last; the oldest is dropped
        while len(_BASELINES) > _BASELINES_MAX:
            _BASELINES.popitem(last=False)
        text = (instructions or "").strip()
        if text not in baseline.prompts and len(baseline.prompts) < 2:
            baseline.prompts.add(text)
        baseline.words = words if baseline.words is None else baseline.words & words
        baseline.numbers = numbers if baseline.numbers is None else baseline.numbers & numbers
        varied = len(baseline.prompts) >= 2
        common_words, common_numbers = set(baseline.words), set(baseline.numbers)
    own_words, own_numbers = _prompt_details(instructions)
    if not varied:
        return own_words, own_numbers
    return (words - common_words - _FUNCTION_WORDS) | own_words, (numbers - common_numbers) | own_numbers


def _same_number(said: str, detail: str) -> bool:
    """One number, written with or without its country code or leading part
    ("98765 43210" and "+91 98765 43210"): equal, or the longer ends with the shorter of
    at least 4 digits."""
    if said == detail:
        return True
    short, long = sorted((said, detail), key=len)
    return len(short) >= 4 and long.endswith(short)


def _repeats_prompt_details(answer: str, question: str, instructions: str,
                            agent_key: Optional[tuple] = None) -> bool:
    """Whether the answer repeats a detail the system prompt gave about this caller
    ("Hi Asha! We open at nine.", "account 99812") that the question itself did not
    contain. Such an answer was shaped by this caller's details and is never shared."""
    words, numbers = _caller_details(instructions, agent_key)
    if not (words or numbers):
        return False
    asked_words, asked_numbers = set(_words(question)), set(_numbers(question))
    if any(w in words and w not in asked_words for w in _words(answer)):
        return True
    return any(
        _same_number(n, d) for n in _numbers(answer) if n not in asked_numbers for d in numbers
    )


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


# Words a request opens with before what it asks: "please", "can you".
_REQUEST_OPENERS = _DISCOURSE | {"can", "could", "will", "would", "you", "kindly"}


def _clause_starts(text: str) -> List[List[str]]:
    """Each clause's words from where its request starts: "Okay, can you answer in Spanish"
    gives ["answer", "in", "spanish"]."""
    starts = []
    for clause in _CLAUSES.split(text):
        words = _words(clause)
        while words and words[0] in _REQUEST_OPENERS:
            words = words[1:]
        if words:
            starts.append(words)
    return starts


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


# An answer that does not answer (a question back, "I'm not sure", a refusal) is spoken but
# never saved: cached, it becomes every later caller's answer, and it keeps rephrasings of the
# question from matching a real answer.
_NON_ANSWER_PHRASES = (
    "could you let me know", "could you tell me", "can you tell me", "could you clarify",
    "can you clarify", "could you specify", "can you specify", "could you provide",
    "can you provide", "please clarify", "please specify", "please provide", "let me know the ",
    "let me know which", "let me know what", "let me know your", "what do you mean",
    "which one do you mean", "i'm not sure", "i am not sure", "i don't know", "i do not know",
    "i can't help", "i cannot help", "i can't answer", "i cannot answer", "i'm unable to help",
    "i am unable to help", "i'm unable to answer", "i am unable to answer", "i'm unable to assist",
    "i am unable to assist", "i'm unable to find", "i am unable to find", "i don't have access", "i do not have access", "i don't have information",
    "i do not have information", "need more information", "need more details",
    "i need more information", "i need more details", "i'm not able to help", "i am not able to help",
    "i'm not able to answer", "i am not able to answer", "i'm not able to access", "i am not able to access",
    "i'm afraid i don't", "i'm afraid i can't", "i'm afraid i do not", "i'm afraid i cannot",
    "i'm not able to share", "i am not able to share", "i'm not able to provide", "i am not able to provide",
    "i can't provide", "i cannot provide", "i can't share", "i cannot share",
    "i can't determine", "i cannot determine", "i'm unable to determine", "i am unable to determine",
    "i'm not able to determine", "i am not able to determine", "i couldn't determine", "i could not determine",
    "it is impossible to determine", "it's impossible to determine", "it is not possible to determine",
    "it's not possible to determine",
)


# What follows "..., but" when a reply only points elsewhere: "but you can check a map".
_REDIRECTS = ("you ", "you'll", "you'd", "a quick search", "a search", "an online search", "i recommend", "i suggest", "i'd ", "i would ", "i can ", "please", "try", "check",
              "consider", "if you", "it's best", "it is best", "it would be best")


# Openers that soften a non-answer without changing it: "Unfortunately I do not know".
_SOFTENERS = ("unfortunately ", "sadly ", "sorry ", "hmm ", "well ", "but ")


_SENTENCE = re.compile(r"[^.!?]+[.!?]*")


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


def _is_non_answer(answer: str) -> bool:
    text = " ".join((answer or "").lower().replace("\u2019", "'").split())
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip(" .!?")]
    if not sentences:
        return False
    if all(s.endswith("?") for s in sentences):
        return True
    # Only when the answer opens with it, after at most a short courtesy or softener: "Sure! Could you
    # tell me which city?" and "Sarah, could you tell me which order?" ask back; "To get
    # a refund, please provide your receipt." answers.
    leads = [sentences[0]]
    if len(sentences) > 1 and len(sentences[0].split()) <= 4:
        if all(s.endswith("?") for s in sentences[1:]):
            return True  # "Happy to help! Which product do you mean?"
        leads.append(sentences[1])
    head, _, rest = sentences[0].partition(", ")
    if rest and len(head.split()) <= 3:
        leads.append(rest)
    leads = [next((lead[len(w):] for w in _SOFTENERS if lead.startswith(w)), lead) for lead in leads]
    # "I can't determine the exact date, but historians place it around 1200 BC." answers;
    # "I cannot determine your location, but you can check a map." does not.
    return any(lead.startswith(phrase) and not ("determine" in phrase and _answers_after_but(lead))
               for lead in leads for phrase in _NON_ANSWER_PHRASES)


def _answers_after_but(lead: str) -> bool:
    _, but, after = lead.partition(", but ")
    return bool(but) and not after.startswith(_REDIRECTS)


def _private_chain(chain: List[str], min_words: int = 0) -> bool:
    """A chain is private when any turn of it is, or when its root ("Priya Sharma.",
    "Bipolar.") is too short to stand alone or neither asks nor requests anything."""
    root = (chain[0] or "").strip() if chain else ""
    if chain and (len(root.split()) < min_words or not _asks(root)):
        return True
    return any(_is_personal(turn) or _lookup_only(turn) for turn in chain)
