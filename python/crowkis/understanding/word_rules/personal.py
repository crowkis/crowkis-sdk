"""Personal turns: the caller's own records, details, identity and sensitive matters."""

from __future__ import annotations

import re
from typing import List, Optional

from .text import (  # noqa: F401
    _ACTION_VERBS,
    _AUXILIARIES,
    _CALLER_KINDS,
    _CLAUSES,
    _CLAUSE_MARKERS,
    _DISCOURSE,
    _FIRST_PERSON,
    _FUNCTION_WORDS,
    _GREETINGS,
    _ID_WORDS,
    _MATTERS,
    _MONTHS,
    _NUMBER_WORDS,
    _ORDINALS,
    _OWNED_THINGS,
    _OWNERS,
    _PERSONAL_MATTERS,
    _PERSON_CUES,
    _POSSESSIVES,
    _QUESTION_LEADS,
    _RELATIONS,
    _REPLY_LEADS,
    _REQUEST_VERBS,
    _SENSITIVE,
    _SINGLE_WORDS,
    _SOFT_REPLY_LEADS,
    _STATEMENT_SUBJECTS,
    _STATE_WORDS,
    _STREET_WORDS,
    _TRIM,
    _UNIT_WORDS,
    _WH_WORDS,
    _amount,
    _capitalised_name,
    _contains,
    _first_words,
    _has_digit,
    _has_phrase,
    _proper_nouns,
    _unknown,
    _words,
)
from .phrases import (  # noqa: F401
    _ACTION_LEADS_BY_FIRST,
    _CONNECTIVES,
    _CRISIS_PHRASES,
    _EMAIL_ENDINGS,
    _MAX_TURN_CHARS,
    _SOMEONE,
    _SPACED_DIGITS,
    _THIRD_PERSON,
)
from .urgent import (  # noqa: F401
    _urgent,
)


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


_INTRO_AFTER_GREETING = (("i", "am"), ("i", "m"), ("this", "is"), ("it", "s"), ("my", "name"))


# A verb first is a request only when it acts on something ("set a timer", "turn
# off the lights", "cancel my order"). A verb before a noun is search-style
# phrasing: "refund status for john", "return policy for shoes".
_ACTION_OBJECTS = (_FUNCTION_WORDS | {
    "a", "an", "some", "another", "all", "everything", "up", "off", "out", "down", "over",
    "back", "away", "ahead", "his", "her", "our", "my", "me", "us",
}) - {"you", "i", "we", "they"}  # "do you ship abroad" asks, "do it" tells


_STATEMENT_VERBS = frozenset({"is", "are", "was", "were", "s", "costs", "cost", "means", "includes", "has", "have"})


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
    # a recap of what the caller told this call
    ("so", "far"), ("know", "about", "me"), ("have", "on", "me"), ("have", "about", "me"),
    ("on", "file", "for", "me"), ("recap",),
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


_EMAIL = re.compile(r"[A-Za-z0-9._%+-]@[A-Za-z0-9-]")


# An IPv4 address: personal data, as an IPv6 address already counts (its digit runs).
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"


_IPV4 = re.compile(r"(?<![0-9.])" + _OCTET + r"(?:\." + _OCTET + r"){3}(?![0-9]|\.[0-9])")


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


_DATE = re.compile(r"(?<![0-9])[0-9]{1,2}[/.-][0-9]{1,2}[/.-][0-9]{2,4}(?![0-9])")


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


_FIRST_PERSON_SUBJECTS = frozenset({"i", "we"})


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


# What a person, not a product, does after an opening auxiliary: "does Mohit have".
_PERSON_VERBS = frozenset(
    {
        "have", "has", "had", "need", "want", "pick", "get", "come", "coming", "call", "called",
        "know", "live", "book", "booked", "order", "ordered", "pay", "paid", "arrive", "arrived",
        "still", "already", "sign", "signed", "speak", "talk", "collect", "collects", "visit", "attend",
    }
)


# "Can I speak to Meera", "pls connect to raghav sir": a person asked for by name.
_ASK_FOR = (
    ("speak", "to"), ("speak", "with"), ("talk", "to"), ("talk", "with"), ("connect", "to"),
    ("connect", "me", "to"), ("transfer", "to"), ("transfer", "me", "to"), ("ask", "for"),
    ("put", "me", "through", "to"),
)


_ASK_FOR_BY_FIRST = _first_words(_ASK_FOR)


_POSSESSIVE_NAME = re.compile(r"([^\W\d_]+)['’]s\s+([^\W\d_]+)")


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
