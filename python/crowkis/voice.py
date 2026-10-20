from __future__ import annotations

import concurrent.futures
import logging
import re
import string
import threading
import time
import weakref
from typing import Any, Callable, Dict, List, Optional

from .agent import Agent, _voice_addon_missing
from .client import CrowkisClient, CrowkisError

# The server takes at most this per count in one report.
_REPORT_MAX = 1_000_000

_LOG = logging.getLogger("crowkis")

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


# --- Turns whose answer must never be shared ------------------------------------------
# Kept word for word with the Node SDK (voice.js). Each group fails closed: a
# match means "answer fresh, never cache".

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
    if _DIGITS.search(text) or _EMAIL.search(text) or _reads_out_digits(text, words):
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


# How many follow-ups back a turn may lean on before it is treated as unresolvable.
_CHAIN_LIMIT = 6

_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="crowkis-voice")


# What _record_model_turn did with an answer; the two that put it in the shared cache.
_STORED = frozenset({"saved", "template"})


class _Outcome(str):
    """An outcome word ("saved", "kept", ...) that also says, in ``why``, why an answer
    was not stored. Compares and serialises as the plain word."""

    why: str

    def __new__(cls, word: str, why: str = "") -> "_Outcome":
        outcome = super().__new__(cls, word)
        outcome.why = why
        return outcome


class TurnDecision:

    def __init__(
        self,
        action: str,
        *,
        text: Optional[str] = None,
        audio: Optional[bytes] = None,
        confidence: float = 0.0,
        reason: str = "",
    ) -> None:
        self.action = action
        self.text = text
        self.audio = audio
        self.confidence = confidence
        self.reason = reason
        # For a model turn: what the model must read, and whether its answer is shared.
        # None means "the whole call", and then the answer is never shared.
        self.messages: Optional[List[Dict[str, str]]] = None
        self.cacheable = False
        # Which turn of the call this is; an answer recorded for an older turn is dropped.
        self.turn = 0
        # After answer(): whether the model's answer was stored, and if not, why.
        self.stored = False
        self.not_stored = ""
        self._empty = False
        self._audio_shareable = False
        # Set by decide(): the session that made it (a weak reference, so a kept
        # decision never keeps a call alive) and, for a model turn, what the caller
        # said, so record() takes a decision only from its own session, and only once.
        # The caller's words are dropped once recorded.
        self._session: Optional["weakref.ReferenceType[VoiceSession]"] = None
        self._said: Optional[str] = None
        self._recorded = False

    @property
    def audio_shareable(self) -> bool:
        """Whether the spoken audio of this answer may go to the shared audio cache:
        not for an answer filled with this caller's values."""
        return self._audio_shareable

    @property
    def served_from_cache(self) -> bool:
        return self.action == "serve"

    @property
    def served_from_filler(self) -> bool:
        return self.action == "filler"

    @property
    def needs_model(self) -> bool:
        return self.action == "infer"

    @property
    def empty(self) -> bool:
        """After answer(): the model was asked and said nothing (the action stays
        "infer"); retry, or speak a fallback."""
        return self._empty

    def __repr__(self) -> str:
        return (
            f"TurnDecision({self.action!r}, confidence={self.confidence:.4f}, "
            f"reason={self.reason!r})"
        )


class VoiceSession:

    def __init__(
        self,
        agent: Agent,
        *,
        voice: str,
        serve_above: float = 0.92,
        min_words: int = 3,
        synthesise: Optional[Callable[[str], bytes]] = None,
        ttl: Optional[int] = None,
        latency_budget_ms: Optional[float] = None,
        fillers: Optional[Dict[str, str]] = None,
        values: Optional[Dict[str, str]] = None,
        commitments: str = "exact",
        short_turns: bool = False,
        share_templates: bool = False,
        language: str = "und",
        speed: str = "1",
        audio_format: str = "default",
        bytes_per_second: Optional[int] = None,
    ) -> None:
        if not 0.0 <= serve_above <= 1.0:
            raise ValueError(f"serve_above must be in 0..1, got {serve_above}")
        if commitments not in _COMMITMENTS:
            raise ValueError(
                f"commitments must be one of {sorted(_COMMITMENTS)}, got {commitments!r}"
            )
        if latency_budget_ms is not None and latency_budget_ms <= 0:
            raise ValueError(
                f"latency_budget_ms must be positive, got {latency_budget_ms}"
            )
        voice = (voice or "").strip()
        if not voice:
            raise ValueError(
                "VoiceSession requires a voice id. Cached audio is only reusable for "
                "the voice that produced it, and switching voices mid-call is audible"
            )
        self.agent = agent
        self.voice = voice
        # What changes the sound besides the voice: a clip is reused only when
        # all of these match (Voice add-on).
        self.language = language
        self.speed = speed
        self.audio_format = audio_format
        self.bytes_per_second = bytes_per_second
        self._reported: Dict[str, int] = {}
        self.serve_above = serve_above
        self.min_words = min_words
        self.synthesise = synthesise
        self.ttl = ttl
        self.latency_budget_ms = latency_budget_ms
        self.commitments = commitments
        self.short_turns = short_turns
        # Off by default: a template is cut from an answer the model wrote with the whole
        # call in view, so what is left outside its slots can hold what the caller said.
        self.share_templates = share_templates
        self.values: Dict[str, str] = {}
        self.transcript: List[Dict[str, str]] = []
        self.served = 0
        self.inferred = 0
        self.filled = 0
        self.refused_short = 0
        self.refused_private = 0
        self.uncacheable_personal = 0
        self.over_budget = 0
        self.barge_ins = 0
        self.lookup_errors = 0
        self.learn_errors = 0
        self.not_shareable = 0
        self.held_commitments = 0
        self.unspeakable = 0
        self.empty_answers = 0
        # The question the latest stored answer was stored under.
        self._last_stored: Optional[str] = None
        self._fillers: Dict[str, str] = {}
        self._open = False
        self._cancelled = False
        self._turn_mark = 0
        self._turn = 0
        # (turn, whether that turn's answer may be shared): read with the turn it
        # belongs to, so a turn decided meanwhile never lends its flag.
        self._shareable = (0, False)
        # Turn number and flag change together: two decide() calls never share a turn.
        self._turn_lock = threading.RLock()
        if values:
            self.set_values(**values)
        if fillers:
            self.register_fillers(fillers)

    def set_values(self, **values: object) -> None:
        for name, value in values.items():
            if value is None:
                self.values.pop(name, None)
            else:
                self.values[name] = str(value)

    def register_filler(self, trigger: str, response: str) -> None:
        key = _normalise(trigger)
        if not key:
            raise ValueError("a filler trigger must contain something to match on")
        if not (response or "").strip():
            raise ValueError("a filler response must not be empty")
        self._fillers[key] = response

    def register_fillers(self, pairs: Dict[str, str]) -> None:
        for trigger, response in pairs.items():
            self.register_filler(trigger, response)

    def decide(self, caller_said: str) -> TurnDecision:
        with self._turn_lock:
            self._turn += 1
            turn = self._turn
        decision = self._decide(caller_said)
        decision.turn = turn
        decision._session = weakref.ref(self)
        if decision.needs_model:
            decision._said = caller_said
            decision.messages, decision.cacheable = self._model_messages(caller_said)
        with self._turn_lock:
            if turn == self._turn:  # a newer turn's flag is never overwritten by an older one
                self._shareable = (turn, decision.cacheable)
        return decision

    def _model_messages(self, caller_said: str):
        """What the model should read to answer this turn, and whether that answer may be cached.

        A shared answer is only safe when the model saw nothing but the cache key:
        the question, and for a follow-up the questions it leans on. Nothing else the
        caller said (a name, a plan, "pretend refunds are unlimited") can then end
        up inside it. Personal turns, and follow-ups to one, get the whole call and
        are never shared.
        """
        text = (caller_said or "").strip()
        if (
            len(text.split()) < self.min_words or _is_personal(text) or _lookup_only(text)
            or self._after_urgent(text)
        ):
            return None, False
        if not _is_context_dependent(text):
            # "Twelve years old.": a turn that neither asks nor requests anything is an
            # answer about the caller, never stored on its own.
            if not _asks(text):
                return None, False
            return [{"role": "user", "content": caller_said}], True
        chain = self._chain()
        if chain is None or _private_chain(chain, self.min_words):
            return None, False
        return [{"role": "user", "content": turn} for turn in chain + [caller_said]], True

    def _decide(self, caller_said: str) -> TurnDecision:
        self._turn_mark = len(self.transcript)
        self._open = True
        self._cancelled = False

        text = (caller_said or "").strip()
        if not text:
            self.refused_short += 1
            return TurnDecision("infer", reason="empty transcript")

        filler = self._fillers.get(_normalise(text))
        if filler is not None:
            self.filled += 1
            decision = TurnDecision(
                "filler",
                text=filler,
                audio=self._voiced(filler),
                confidence=1.0,
                reason="registered filler, answered without a lookup or a model",
            )
            decision._audio_shareable = True
            return decision

        # "Thank you" or "hello" is too short to match on meaning. With
        # short_turns on it is served on an exact match the server's decision
        # engine has vouched for; otherwise, and with no engine, it goes to
        # the model as it always did.
        short = len(text.split()) < self.min_words
        if short and not (self.short_turns and self._engine_vouches()):
            self.refused_short += 1
            return TurnDecision("infer", reason="transcript too short to match safely")

        personal = _is_personal(text)
        if personal and not self.values:
            self.refused_private += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "the caller asked about their own records and this session has no "
                    "values to fill a shared answer shape with, so nothing can be "
                    "answered from cache without one caller's answer reaching the next"
                ),
            )

        context_bound = _is_context_dependent(text)
        keyed = self._context_key(caller_said, text)
        if keyed is None:
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "the utterance only has meaning against an earlier turn and this "
                    "call has none, so no cache key can be built for it"
                ),
            )
        if (context_bound and _private_chain(self._chain() or [], self.min_words)) or self._after_urgent(text):
            self.refused_private += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "a follow-up to a private turn of this call: its answer depends on "
                    "what this caller said, so it is never answered from a shared cache"
                ),
            )

        started = time.monotonic()
        lookup = lambda: self.agent.ask(  # noqa: E731
            keyed,
            serve_above=self.serve_above,
            cheap_above=min(0.60, self.serve_above),
            template=personal,
            threshold=_CONTEXT_BOUND_THRESHOLD if context_bound or short else None,
        )
        try:
            if self.latency_budget_ms is None:
                hit = lookup()
            else:
                # A hard deadline, not a check after the fact: a slow or hung
                # cache must never hold a live call past its budget.
                hit = _LOOKUPS.submit(lookup).result(timeout=self.latency_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.over_budget += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    f"lookup passed the {self.latency_budget_ms}ms voice budget; "
                    "a late hit is worse than a fast miss"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — an unreachable cache means "ask the model"
            self.lookup_errors += 1
            self.inferred += 1
            return TurnDecision("infer", reason=f"cache unavailable ({type(exc).__name__}); asking the model")
        took_ms = (time.monotonic() - started) * 1000.0
        # Cut off a slow lookup above, and refuse one that finished after the budget.
        if self.latency_budget_ms is not None and took_ms > self.latency_budget_ms:
            self.over_budget += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                confidence=hit["confidence"],
                reason=(
                    f"lookup took {took_ms:.1f}ms, past the {self.latency_budget_ms}ms "
                    "voice budget; a late hit is worse than a fast miss"
                ),
            )

        if hit["route"] != "cache":
            self.inferred += 1
            return TurnDecision(
                "infer",
                confidence=hit["confidence"],
                reason=f"confidence below the spoken-answer bar of {self.serve_above}",
            )

        answer = hit["answer"]
        if personal:
            answer = _fill(answer, self.values)
            if answer is None:
                self.refused_private += 1
                self.inferred += 1
                return TurnDecision(
                    "infer",
                    confidence=hit["confidence"],
                    reason=(
                        "the shared answer shape has a slot this call has no value "
                        "for; speaking a half-filled answer is worse than a model call"
                    ),
                )

        held = self._held(hit, answer, short)
        if held:
            self.inferred += 1
            return TurnDecision("infer", confidence=hit["confidence"], reason=held)

        self.served += 1
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": answer})
        decision = TurnDecision(
            "serve",
            text=answer,
            audio=self._voiced(answer, cacheable=not personal),
            confidence=hit["confidence"],
            reason="confident cache hit",
        )
        decision._audio_shareable = not personal
        return decision

    def _engine_vouches(self) -> bool:
        """Whether the server judges what it caches, asked inside this call's
        budget: a slow answer is a no for this turn, and is there for the next."""
        if self.latency_budget_ms is None:
            return self.agent.decides()
        try:
            return _LOOKUPS.submit(self.agent.decides).result(timeout=self.latency_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            return False

    def _held(self, hit: dict, answer: str, short: bool) -> Optional[str]:
        """Why a confident hit still goes to the model, if it does."""
        if short and not (hit.get("vouched") and hit.get("exact")):
            return (
                "a short turn is only answered from cache once the answer has been "
                "judged to stand on its own, and this one has not"
            )
        if hit.get("commitment") and not _COMMITMENTS[self.commitments](hit):
            self.held_commitments += 1
            return (
                "the cached answer is a commitment (a price, a refund, a policy) and "
                f"commitments={self.commitments!r} does not allow speaking this match"
            )
        if not _speakable(answer):
            self.unspeakable += 1
            return "the cached answer was written for a screen (a link, code or markup)"
        return None

    def cancel(self) -> bool:
        if not self._open:
            return False
        self._open = False
        self._cancelled = True
        self.barge_ins += 1
        del self.transcript[self._turn_mark:]
        return True

    def answer(
        self,
        caller_said: str,
        llm: Callable[[List[Dict[str, str]]], str],
        *,
        system: Optional[str] = None,
    ) -> TurnDecision:
        """Run one caller turn end to end: cache, or the model, then remember the answer.

        ``llm`` is called with exactly the messages Crowkis chose for this turn: the
        question alone (or with the question before it) when the answer may be shared,
        the whole call when it may not. ``system`` is the app's own instructions, the
        same for every caller, and is put first. The returned decision carries the
        text to speak, from the cache or from the model, and ``stored`` /
        ``not_stored`` say whether the model's answer was cached and why not. A
        model that says nothing sets ``empty``: retry, or speak a fallback.
        """
        decision = self.decide(caller_said)
        if not decision.needs_model:
            return decision
        messages = decision.messages
        if messages is None:
            messages = self.injections() + [{"role": "user", "content": caller_said}]
        if system:
            messages = [{"role": "system", "content": system}] + messages
        # Straight to the recording step: answer() made this decision itself, so a
        # subclass whose decide() returns its own decision object keeps working.
        decision._said = caller_said
        return self._record_decision(decision, llm(messages), private=False)

    def record(self, decision: TurnDecision, answer: Optional[str], *, private: bool = False) -> TurnDecision:
        """Save the answer to a turn you sent to your own model: decide(), then call
        the model with ``decision.messages``, then record(decision, its answer).

        The same rules as answer() decide what happens to it: shared with other
        callers only when decide() said it may be (``decision.cacheable``), kept to
        this call otherwise, and dropped when the caller talked over it (cancel()) or
        a newer turn was decided since. ``private=True`` keeps a shareable answer to
        this call, e.g. one built from a tool's result. Never raises for the server:
        a refused write is reported, not thrown.

        Returns ``decision`` with ``text`` set to the answer and ``stored`` /
        ``not_stored`` / ``empty`` filled in, as answer() does. Raises ValueError for a
        decision this session did not make, one that did not need the model (served
        from the cache or a filler), or one already recorded.
        """
        if not isinstance(decision, TurnDecision):
            raise ValueError(f"record() takes the TurnDecision decide() returned, got {type(decision).__name__}")
        with self._turn_lock:  # two threads recording one decision: only one gets through
            if decision._recorded:
                raise ValueError("record() got a decision that was already recorded")
            owner = decision._session() if decision._session is not None else None
            if owner is not self:
                raise ValueError(
                    "record() takes a decision from this session's decide(); one from another "
                    "session (another call) or made by hand is refused"
                    if decision._session is None else
                    "record() got a decision from another session: each call's answers are "
                    "recorded in the session that decided them"
                )
            if not decision.needs_model:
                where = "a filler" if decision.served_from_filler else "the cache"
                raise ValueError(
                    f"record() is for a turn that needed the model; this one was answered "
                    f"by {where} ({decision.action!r})"
                )
            decision._recorded = True
        return self._record_decision(decision, answer, private=private)

    def _record_decision(self, decision: TurnDecision, answer: Optional[str], *, private: bool) -> TurnDecision:
        """record() and answer(): store the answer and fill in the decision."""
        decision._recorded = True
        said, decision._said = decision._said, None
        decision.text = answer
        outcome = self._record_model_turn(said, answer, turn=decision.turn, private=private)
        decision.stored = outcome in _STORED
        why = "" if decision.stored else (outcome.why or str(outcome))
        decision.not_stored = why
        if not (decision.text or "").strip():
            decision._empty = True
            decision.reason = "the model returned an empty answer; retry or speak a fallback"
        elif why:
            decision.reason = f"{decision.reason}; not stored: {why}"
        return decision

    def record_private_turn(self, caller_said: str, model_said: str) -> None:
        """Keep a turn in this call's transcript and never cache it.

        For a model that holds the whole conversation itself (a realtime speech
        model): it cannot be given ``decision.messages``, so nothing it says is shared.
        """
        if self._cancelled:
            return
        self._open = False
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": model_said})
        with self._turn_lock:
            if self._shareable[1]:
                self.not_shareable += 1
            self._shareable = (0, False)

    def _record_model_turn(
        self, caller_said: str, model_said: str, *, turn: Optional[int] = None, private: bool = False
    ) -> str:
        """Record the model's answer to the turn decide() last handled, and cache it if allowed.

        Only an answer written from ``decision.messages`` reaches this, so it is shared
        exactly when decide() said it may be. ``turn`` is the decision's turn: an answer
        to a turn the caller talked over, or to one before the latest, is dropped, so it
        never lands on later words. ``private`` keeps it to this call whatever the turn
        was (an answer built from a tool's result). Never raises: a refused write
        (security pipeline, tenant limit, cache down) must not end a call.

        Returns what happened to the answer: ``saved`` (shared), ``template`` (shared
        as a shape, this caller's values removed), ``kept`` (the model read the whole
        call, or a tool's result, so it stays in this call), ``private`` (personal, or
        repeats this caller's details), ``non_answer``, ``not_saved`` (a follow-up with
        nothing to key it to), ``refused`` (the write failed) or ``interrupted`` (talked
        over, or the caller moved on before it was complete). The returned string's
        ``why`` says it in words.
        """
        with self._turn_lock:
            expected = self._turn if turn is None else turn
            if self._cancelled or expected != self._turn:
                return _Outcome("interrupted", "the caller moved on before this answer was complete")
            self._open = False
            shareable, self._shareable = self._shareable, (0, False)
        cacheable = shareable[1] and shareable[0] == expected and not private
        if not (model_said or "").strip():
            self.empty_answers += 1
            return _Outcome("non_answer", "the model returned an empty answer")
        text = (caller_said or "").strip()
        keyed = self._context_key(caller_said, text)
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": model_said})
        if keyed is None:
            return _Outcome("not_saved", "a follow-up with no earlier turn to key it on")
        if private:
            self.not_shareable += 1
            return _Outcome("kept", "kept to this call: the answer was built from a tool's result")
        try:
            if _is_personal(text):
                if self._learn_personal(keyed, model_said):
                    return _Outcome("template")
                return _Outcome("private", "about this caller, with no declared value to make a shared answer shape from")
            if not cacheable:
                self.not_shareable += 1
                return _Outcome("kept", "kept to this call: the answer depends on what this caller said")
            if _leaks(model_said, self.values):
                self.not_shareable += 1
                return _Outcome("private", "kept to this call: the answer contains a value declared for this call")
            self.agent.learn(keyed, model_said, ttl=self.ttl)
            self._last_stored = keyed
            return _Outcome("saved")
        except Exception as error:  # noqa: BLE001 — see docstring
            self.learn_errors += 1
            why = f"the server refused the write: {str(error) or type(error).__name__}"
            _LOG.warning("crowkis voice answer not stored, %s", why)
            return _Outcome("refused", why)

    def injections(self) -> List[Dict[str, str]]:
        return list(self.transcript)

    def stats(self) -> dict:
        total = self.served + self.inferred + self.filled
        def pct(n: int) -> float:
            return round(100.0 * n / total, 2) if total else 0.0

        return {
            "turns": total,
            "served_from_cache": self.served,
            "answered_by_filler": self.filled,
            "model_calls": self.inferred,
            "refused_too_short": self.refused_short,
            "refused_to_share_a_private_answer": self.refused_private,
            "uncacheable_personal": self.uncacheable_personal,
            "missed_latency_budget": self.over_budget,
            "barge_ins": self.barge_ins,
            "cache_unavailable": self.lookup_errors,
            "failed_writes": self.learn_errors,
            "not_shareable": self.not_shareable,
            "commitments_sent_to_model": self.held_commitments,
            "unspeakable_answers": self.unspeakable,
            "empty_answers": self.empty_answers,
            "cache_hit_pct": pct(self.served),
            "filler_hit_pct": pct(self.filled),
            "model_calls_avoided_pct": pct(self.served + self.filled),
        }

    def _reportable(self) -> Dict[str, int]:
        """The counts the Voice page shows, by the server's names."""
        return {
            "turns": self.served + self.inferred + self.filled,
            "served_from_cache": self.served,
            "filler_hits": self.filled,
            "model_calls_avoided": self.served + self.filled,
            "private_turns": self.refused_private + self.uncacheable_personal,
            "barge_ins": self.barge_ins,
            "latency_misses": self.over_budget,
            "empty_answers": self.empty_answers,
        }

    def report_stats(self) -> bool:
        """Send this session's counts since its last report to the Voice page
        (the server's Voice add-on). False when the server has no Voice add-on.
        Nothing is lost: what a failed report did not send goes with the next."""
        now = self._reportable()
        sent = {
            name: min(count - self._reported.get(name, 0), _REPORT_MAX)
            for name, count in now.items()
            if count > self._reported.get(name, 0)
        }
        if not sent:
            return True
        try:
            self.agent._client.cvoicestat(sent, tenant=self.agent.tenant)
        except CrowkisError as err:
            if _voice_addon_missing(err):
                return False
            raise
        for name, count in sent.items():
            self._reported[name] = self._reported.get(name, 0) + count
        return True

    def _chain(self) -> Optional[List[str]]:
        """The earlier caller turns a follow-up leans on, oldest first: back to the
        latest one that stands on its own. None when there is no such turn."""
        chain: List[str] = []
        for turn in reversed(self.transcript):
            if turn["role"] != "user":
                continue
            chain.insert(0, turn["content"])
            if not _is_context_dependent((turn["content"] or "").strip()):
                return chain
            if len(chain) >= _CHAIN_LIMIT:
                return None
        return None

    def _after_urgent(self, text: str) -> bool:
        """A short turn after a private emergency or medical turn ("is he going to be
        okay?", "how do i make her vomit?"): about that turn, so answered with the call."""
        if len(_words(text)) > _FOLLOW_UP_WORDS:
            return False
        earlier = [turn["content"] or "" for turn in self.transcript if turn["role"] == "user"]
        for said in reversed(earlier[-_CHAIN_LIMIT:]):
            words = _words(said)
            if (any(w in _URGENT for w in words) or _urgent(words)) and _is_personal(said):
                return True
            if len(words) > _FOLLOW_UP_WORDS:
                return False
        return False

    def _context_key(self, caller_said: str, text: str) -> Optional[str]:
        if not _is_context_dependent(text):
            return caller_said
        chain = self._chain()
        if chain is None:
            return None
        return " || ".join(chain + [caller_said])

    def _learn_personal(self, keyed: str, model_said: str) -> bool:
        """Store a personal answer as a shape. False when it cannot be made generic,
        or when this session does not share templates."""
        if not self.share_templates:
            self.uncacheable_personal += 1
            return False
        shaped = _abstract(model_said, self.values)
        # The model read the whole call: what is left outside the slots must say nothing
        # of this caller that was not declared (a name, an address, a number, a matter).
        outside = _SLOT.sub(" ", shaped)
        words = _words(outside)
        earlier = [turn["content"] or "" for turn in self.transcript if turn["role"] == "user"]
        undeclared = (
            any(_has_digit(w) or w in _AMOUNT_WORDS or w in _MATTERS for w in words)
            or _reads_out_digits(outside, words) or bool(_EMAIL.search(outside)) or _identifies(outside, words)
            or _carries_call_context(outside, keyed, earlier)
        )
        if (
            self.values
            and _SLOT.search(shaped)
            and not _leaks(shaped, self.values)
            and not undeclared
        ):
            self.agent.learn(keyed, shaped, ttl=self.ttl, template=True)
            return True
        self.uncacheable_personal += 1
        return False

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        if self.synthesise is None:
            return None
        # A text-only session (voice_session() with no voice) has no real voice id to
        # key a clip on: speak, but never read or store a cached clip.
        if not cacheable or getattr(self, "_text_only", False):
            return self.synthesise(answer)
        return self.agent.speak(
            answer,
            self.synthesise,
            voice=self.voice,
            ttl=self.ttl,
            language=self.language,
            speed=self.speed,
            audio_format=self.audio_format,
            bytes_per_second=self.bytes_per_second,
        )


def _private_chain(chain: List[str], min_words: int = 0) -> bool:
    """A chain is private when any turn of it is, or when its root ("Priya Sharma.",
    "Bipolar.") is too short to stand alone or neither asks nor requests anything."""
    root = (chain[0] or "").strip() if chain else ""
    if chain and (len(root.split()) < min_words or not _asks(root)):
        return True
    return any(_is_personal(turn) or _lookup_only(turn) for turn in chain)


# The voice id of a text-only session. Never used as a cache key: every audio path
# checks `_text_only` first.
_TEXT_ONLY_VOICE = "crowkis:text-only"


def voice_session(
    *,
    voice: Optional[str] = None,
    agent_id: str = "voice",
    client: Optional[CrowkisClient] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    auth_token: Optional[str] = None,
    token: Optional[str] = None,
    tenant: Optional[str] = None,
    timeout: Optional[float] = None,
    latency_budget_ms: Optional[float] = 250,
    **options: Any,
) -> VoiceSession:
    """A ready VoiceSession in one call, with defaults for live calls.

    It builds the client and the Agent itself. Server settings not passed here come
    from the environment, then the defaults (see the README, "Connect to your server").
    The defaults differ from a bare VoiceSession because a caller is waiting:

    - ``latency_budget_ms=250``: the longest a turn waits for a cache lookup before it
      goes to the model. ``None`` turns the budget off.
    - ``timeout=1.0`` seconds per server request, with no retries. Saving the model's
      answer happens while the caller waits; a 5 s timeout tried three times would
      leave a stuck server holding the turn for about 15 s. The cost of no retries: a
      request that fails once (the first on each pooled connection after a server
      restart, or a BUSY reply) is not tried again, so that lookup goes to the model or
      that answer is not stored. Pass your own ``client`` for other settings, e.g. for
      ``warm_from_calls``, which should not use this live-call client.

    ``voice`` is the TTS voice id. Without it the session caches text only and never
    reads or stores audio, so two voices can never share a clip; passing
    ``synthesise`` then is an error. Every other VoiceSession option (``serve_above``,
    ``fillers``, ``ttl``, ...) is passed on as it is.

    ``client`` uses a client you built, as it is: its server settings and timeouts are
    yours, so passing ``host``/``port``/``auth_token``/``token``/``tenant``/``timeout`` with
    it is an error, and closing the agent leaves it open.
    """
    if timeout is not None and not timeout > 0:
        raise ValueError(f"timeout must be a positive number of seconds, got {timeout}")
    if client is not None:
        given = [name for name, value in (("host", host), ("port", port), ("auth_token", auth_token),
                                          ("token", token), ("tenant", tenant), ("timeout", timeout))
                 if value is not None]
        if given:
            raise ValueError(
                f"voice_session() got client= and {', '.join(given)}: a client passed in is "
                "used as it is, so set these on the client instead"
            )
    if voice is None and options.get("synthesise") is not None:
        raise ValueError(
            "voice_session() got synthesise= without voice=. Cached audio is keyed on the "
            "voice that spoke it: pass your TTS voice id, or leave out synthesise to cache text only"
        )
    owns_client = client is None
    if client is None:
        client = CrowkisClient(
            host, port, auth_token=auth_token, token=token, tenant=tenant,
            timeout=1.0 if timeout is None else timeout, max_retries=0,
        )
    agent = Agent(agent_id, client=client, tenant=client.tenant)
    agent._owns_client = owns_client
    session = VoiceSession(
        agent,
        voice=_TEXT_ONLY_VOICE if voice is None else voice,
        latency_budget_ms=latency_budget_ms,
        **options,
    )
    session._text_only = voice is None
    return session


def warm_from_calls(agent: Agent, calls, *, wait: float = 30.0) -> dict:
    """Fill the cache from past calls, so it is useful on the first day.

    `calls` is an iterable of calls, each a list of `(caller_said, agent_said)`
    turns in order. A follow-up is kept with the turn it depends on, and
    nothing is spoken or synthesised.

    It needs the server's decision engine, holding answers until it has judged
    them (the default), and refuses to run otherwise. A past agent turn can
    hold details the caller never said aloud (an address looked up, a
    balance), which the live rules cannot see in a transcript; the engine
    reads every answer before anyone is served it.

    Returns totals. After each call it gives the engine up to `wait` seconds
    to catch up; `stalled` is true when it stopped early because three calls
    in a row were not judged in that time.
    """
    if not (agent.decides() and agent._holds):
        raise RuntimeError(
            "warm_from_calls needs the server's decision engine, holding answers until it has "
            "judged them (CROWKIS_DECIDE_UPSTREAM set, CROWKIS_DECIDE_SERVE_UNJUDGED not set): "
            "otherwise a past answer holding one caller's details could be shared before it is checked"
        )
    totals = {"calls": 0, "turns": 0, "kept_private": 0, "failed_writes": 0, "stalled": False}
    stalls = 0
    for call in calls:
        session = VoiceSession(agent, voice="warm-start")
        earlier: List[str] = []
        for caller_said, agent_said in call:
            # The same rule as a live turn picks the candidates. A past answer
            # was written with the whole call in view, so one that repeats what
            # identified this caller is kept out here, and the engine reads the
            # rest before anyone is served them.
            keyed = session._context_key(caller_said, (caller_said or "").strip()) or caller_said
            _, cacheable = session._model_messages(caller_said)
            session._shareable = (session._turn, cacheable and not _carries_call_context(agent_said, keyed, earlier))
            session._record_model_turn(caller_said, agent_said)
            earlier.append(caller_said)
            totals["turns"] += 1
        totals["calls"] += 1
        totals["kept_private"] += session.not_shareable + session.uncacheable_personal
        totals["failed_writes"] += session.learn_errors
        # Let the engine catch up before the next call: it judges a bounded
        # number of answers at a time and refuses what does not fit.
        stalls = 0 if _judged_in_time(agent, session._last_stored, wait) else stalls + 1
        if stalls >= 3:
            totals["stalled"] = True
            break
    return totals


def _judged_in_time(agent: Agent, query: Optional[str], seconds: float) -> bool:
    """False when the engine was still working on `query` after `seconds`."""
    deadline = time.monotonic() + seconds
    while query is not None and time.monotonic() < deadline:
        try:
            view = agent.explain(query)
        except Exception:  # noqa: BLE001 — cannot ask, so there is nothing to wait for
            return True
        if not isinstance(view, dict) or not view.get("pending"):
            return True
        time.sleep(min(0.2, seconds))
    return query is None


__all__ = ["VoiceSession", "TurnDecision", "warm_from_calls"]
