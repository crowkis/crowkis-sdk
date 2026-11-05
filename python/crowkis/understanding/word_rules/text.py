"""Text primitives the word rules share: words, stems, phrases, numbers, capitals."""

from __future__ import annotations

import re
import string
from typing import Dict, List

_TRIM = string.punctuation + string.whitespace


_WORDS = re.compile(r"[^\W_]+", re.UNICODE)


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


# After "can i", these ask for something for the caller ("can i get a refill of
# my prescription"), not how something is done.
_REQUEST_VERBS = frozenset(
    {
        "get", "have", "receive", "collect", "pick", "order", "book", "reserve", "renew",
        "refill", "extend", "claim", "redeem", "take",
    }
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


# Comma-separated openers that say nothing about the question: "Hi there, quick question, ...".
_PREAMBLES = frozenset({
    "hi", "hello", "hey", "hi there", "hello there", "hey there", "hmm", "um", "uh",
    "okay", "ok", "quick question", "a quick question", "well",
})  # not "so": a leading connective marks a follow-up


def _strip_preamble(text: str) -> str:
    """The turn without leading comma-separated openers from ``_PREAMBLES``; unchanged when nothing
    else is left. shortcut: needs the commas, upgrade with the pluggable understander."""
    rest = text or ""
    while True:
        head, comma, tail = rest.partition(",")
        if not comma or _normalise(head) not in _PREAMBLES or not tail.strip():
            return rest
        rest = tail.lstrip()


def _words(text: str) -> List[str]:
    return _WORDS.findall((text or "").lower())


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


def _contains(words: List[str], phrase: tuple) -> bool:
    span = len(phrase)
    return any(
        tuple(words[start:start + span]) == phrase
        for start in range(len(words) - span + 1)
    )


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


_SPOKEN_DIGITS = frozenset({"zero", "oh", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine"})


_DIGIT_REPEATS = frozenset({"double", "triple"})


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


_CLAUSES = re.compile(r"([,.!?;:]+)")


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


_STREET_WORDS = frozenset(
    {
        "street", "st", "road", "rd", "lane", "ln", "avenue", "ave", "drive", "boulevard", "blvd",
        "marg", "nagar", "colony", "sector", "apartments", "tower", "towers", "block", "society",
        "crescent", "terrace", "court", "place", "square", "highway", "calle", "rua", "rue",
        "avenida", "strasse", "straße", "plaza", "platz",
    }
)


_UNIT_WORDS = frozenset({"flat", "apartment", "apt", "house", "unit", "plot", "suite", "door", "sector", "block"})


def _has_digit(word: str) -> bool:
    return any(c.isdecimal() for c in word)  # any script's digits: "４４０９", "٤٤٠٩"


def _amount(word: str) -> bool:
    return sum(c.isdecimal() for c in word) >= 2 or word in _AMOUNT_WORDS


# Before a capitalised word, these make it a person: "for Rahul", "Dr Mehta",
# "does Mohit have".
_NAME_SLOTS = frozenset({"for", "dr", "prof", "sir", "madam", "miss", "shri", "smt"})


_TITLES = _NAME_SLOTS - {"for"}


_AUXILIARIES = frozenset({"can", "could", "does", "did", "is", "has", "had", "will", "would", "should", "may", "was"})


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


_ROLES = frozenset(
    {
        "someone", "somebody", "anyone", "anybody", "agent", "human", "person", "manager",
        "representative", "operator", "sales", "billing", "accounts", "department", "reception",
        "front", "staff", "engineer", "technician", "executive", "advisor", "adviser", "officer",
    }
)


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


def _capitalised(word: str) -> bool:
    return word[0].isupper() and not word.isupper()


# A capitalised word right after "named", "asks" ... is a person. After an auxiliary it is one only
# when a person's action follows ("did Priya order", "has Sarah paid"): "does Netflix have a plan" is a brand.
# Not "for": the rules cannot tell "for Sarah" from "for Goa" (a model's tag can).
_NAMED_BY = frozenset({"named", "called", "asks", "says"})
_NAME_AUXILIARIES = frozenset({"did", "does", "has", "had", "was", "will"})
_NAME_ACTIONS = frozenset({"order", "ordered", "pay", "paid", "book", "booked", "buy", "bought", "return", "returned",
                           "cancel", "cancelled", "canceled", "refund", "refunded", "call", "called", "ask", "asked",
                           "say", "said", "ship", "shipped", "receive", "received", "complain", "complained"})


def _capitalised_name(text: str, words: List[str]) -> bool:
    """A capitalised name (one word, or two in a row) in a person's place: after a title
    ("Dr. Iyer"), after a word that introduces one ("named Rahul", "did Priya order"), before what
    a person does ("Priya called", "does Mohit have an appointment"), or after one of the caller's
    own matters ("the order for Rahul").
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
        if lead in _TITLES or lead in _NAMED_BY:
            return True  # a title, with or without its period: "Dr. Iyer"
        end = index + 1
        if end < len(tokens) and text[match.end():tokens[end].start()].isspace() and _capitalised(tokens[end].group()):
            if words[end] in _KNOWN_WORDS:
                continue  # "Apple Pay", "Google Maps"
            end += 1
        after = words[end] if end < len(words) else ""
        if after in _POSTPOSITIONS:
            continue
        if lead in _NAME_AUXILIARIES and after in _NAME_ACTIONS:
            return True
        if after in _NAME_VERBS and personal:
            return True
        if first_matter < index and lead not in _PLACE_PREPOSITIONS:
            return True
    return False


def _flatten(text: str) -> str:
    return "".join(_words(text))


_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _proper_nouns(text: str) -> set:
    """Words capitalised mid-sentence ("... my agent Priya said"), lower-cased."""
    found = set()
    text = text or ""
    for match in _TOKEN.finditer(text):
        word = match.group()
        if not word[0].isupper() or word == "I":
            continue
        at = match.start() - 1  # the last non-space character before the word, without slicing the prefix
        while at >= 0 and text[at].isspace():
            at -= 1
        if at >= 0 and text[at] not in ".!?":
            found.add(word.lower())
    return found


# Runs of digits that belong together ("555 0199", "1800-555-0100", "99,812") make one number.
_NUMBER_RUN = re.compile(r"[0-9]+(?:[ ,\-./][0-9]+)*")


def _numbers(text: str) -> List[str]:
    return [re.sub(r"[^0-9]", "", run) for run in _NUMBER_RUN.findall(text or "")]


def _is_decimal_word(word: str) -> bool:
    return any(c.isdecimal() for c in word)


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


_CONTEXT_BOUND_THRESHOLD = 0.995


# How a cached answer that commits the business (a price, a refund, a policy)
# may be spoken. Only matters when the server's decision engine flags one.
_COMMITMENTS = {
    "serve": lambda hit: True,
    "exact": lambda hit: bool(hit.get("exact")),
    "never": lambda hit: False,
}


_CONNECTIVES = frozenset({"and", "so", "but", "or", "also", "then", "aur", "phir", "lekin", "toh"})


# Which question a shared answer was saved for, kept beside it as a plain key (keyed by
# the answer, per tenant), so a hit can be checked against the question it really answers.
# A plain GET/SET key, not the tool cache: that is an Enterprise feature.
_QUESTION_KEY = "crowkis:question:{tenant}:{answer}"


_EMAIL_ENDINGS = frozenset({"com", "in", "org", "net", "co", "io"})


# After these leads, an action verb is a request for the agent to do something.
_ACTION_LEADS = (
    ("please",), ("can", "you"), ("could", "you"), ("will", "you"), ("would", "you"),
    ("i", "want", "to"), ("i", "d", "like", "to"), ("i", "would", "like", "to"),
    ("i", "need", "to"), ("let", "me"), ("i", "wanna"),
)


_ACTION_LEADS_BY_FIRST = _first_words(_ACTION_LEADS)


# A crisis, said in words: private, and what follows it stays with it.
_CRISIS_PHRASES = (
    ("end", "it", "all"), ("kill", "myself"), ("hurt", "myself"), ("harm", "myself"),
    ("want", "to", "die"), ("self", "harm"), ("end", "my", "life"), ("take", "my", "life"),
    ("reason", "to", "live"), ("better", "off", "dead"), ("not", "breathing"), ("heart", "attack"),
    ("ending", "my", "life"), ("ending", "it", "all"), ("end", "myself"), ("kill", "me"),
    ("panic", "attack"), ("wanna", "die"),
)


# Digits read out in groups: "4 4 0 9", "98 765 43". Commas and points are left
# out, so a price ("1,499") or a weight ("1.5") is not an identifier.
_SPACED_DIGITS = re.compile(r"[0-9]+(?:[ \t-]+[0-9]+)+")


# A turn longer than this is private without being read: every rule is linear in
# its length, and a caller's monologue is not a question other callers ask.
_MAX_TURN_CHARS = 1000


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


# What the server puts in a stored answer in place of a caller's detail (its PII scrubber):
# "pii_email_k3fa9". Spoken, it is noise at best.
_PII_PLACEHOLDER = re.compile(
    r"(?<![A-Za-z0-9_])pii_(?:email|phone|natid|card|person|location|ip|dob|passport|iban)_[A-Za-z0-9]+",
    re.IGNORECASE,
)


# The checks below are for past transcripts only (warm_from_calls). A live turn
# needs none of them: its model reads only what decide() hands it. A past
# answer was written with the whole call in view.
# A caller turn that tries to change what the model says for the rest of the call.
_STEERING = (
    ("pretend",), ("from", "now", "on"), ("for", "this", "call"), ("for", "the", "rest"),
    ("ignore",), ("forget",), ("act", "as"), ("you", "are", "now"), ("assume",),
    ("always", "say"), ("tell", "everyone"), ("roleplay",), ("role", "play"),
)
