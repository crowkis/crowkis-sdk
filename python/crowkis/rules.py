"""The word rules every Crowkis conversation decision rests on.

Which turns are personal (never shared), which only mean something after the
previous one (follow-ups), how a personal answer becomes a shape with slots, and
which answers do not answer at all. Pure functions, no I/O. Identical in the Node
SDK (rules.js) and mirrored in the Crowkis server (cache/mod.rs); change all three
together.
"""

from __future__ import annotations

import re
import string
from typing import Dict, List, Optional

_TRIM = string.punctuation + string.whitespace

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)

_SLOT = re.compile(r"\{([^{}\s]+)\}")

_CONTEXT_BOUND_THRESHOLD = 0.995

_POSSESSIVES = frozenset({"my", "our", "mine", "ours"})

_HELD_RECORDS = frozenset(
    {
        "account", "order", "orders", "balance", "booking", "bookings",
        "reservation", "subscription", "payment", "payments", "invoice",
        "invoices", "refund", "delivery", "shipment", "ticket", "claim",
        "policy", "plan", "membership", "appointment", "prescription",
        "statement", "transaction", "transactions", "card", "loan", "mortgage",
        "benefits", "package", "parcel", "return", "returns", "profile",
        "password", "address", "phone", "email", "number", "contract",
        "renewal", "bill", "billing", "charge", "charges", "deposit",
        "withdrawal", "transfer", "case", "complaint", "name", "details",
        "detail", "info", "information", "points", "rewards", "cart", "basket",
        "wallet", "credit", "credits", "history", "purchase", "purchases",
        "username", "warranty", "coupon", "voucher", "code", "otp", "pin", "emi",
    }
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

_CONNECTIVES = frozenset({"and", "so", "but", "or", "also", "then"})

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
_FOLLOW_UP_ENDINGS = frozenset({"too", "also", "instead"})

_ANAPHOR_PHRASES = ("this one", "the second one", "the first one", "the other one")

_ANAPHORS = frozenset({"that", "those", "it", "them", "they", "these", "this"})

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
_CALLER_LEADS = (("as", "a"), ("as", "an"), ("i", "am"), ("i", "m"), ("for",))
_SELF_PHRASES = (
    ("am", "i"), ("do", "i", "qualify"), ("i", "live", "in"), ("i", "am", "from"),
    ("i", "m", "from"), ("i", "am", "based"), ("i", "m", "based"), ("i", "am", "on"),
    ("i", "m", "on"),
)

# A caller describing themself makes the right answer theirs alone: "I'm a farmer", "I am 65", "I have a small business", "my income is low", "which scheme suits someone like me".
# Not an action or a feeling ("I'm looking for", "I'm not sure"), a filler ("I'm a bit"), a generic
# role ("as a customer"), a hypothetical ("if I am late"), or a service ("explain this for me").
_NOT_DESCRIPTION = frozenset({"not", "so", "just", "sure", "unsure", "curious", "interested", "wondering", "confused", "able", "unable", "about", "going", "also", "still", "really", "very", "glad", "happy", "sorry", "ready", "done", "back", "here", "speaking"})
_ARTICLE_FILLERS = frozenset({"bit", "little", "lot", "few", "couple"})
_GENERIC_ROLES = frozenset({"customer", "customers", "user", "users", "buyer", "client", "guest", "visitor", "shopper"})
_HAVE_NOT = frozenset({"question", "questions", "query", "doubt", "quick", "general", "problem"})
_HYPOTHETICAL = frozenset({"if", "when", "whether", "unless", "once"})
_SERVICE_VERBS = frozenset({"explain", "describe", "list", "repeat", "check", "clarify", "define", "translate", "summarise", "summarize", "write", "read", "spell"})
_LIFE_WORDS = frozenset({"income", "salary", "age", "family", "wife", "husband", "son", "daughter", "kids", "children", "child", "parents", "mother", "father", "farm", "business", "company", "shop", "health", "condition", "disability", "pension", "loan", "debt", "religion", "caste"})
_CIRCUMSTANCES = (("i", "have", "been"), ("i", "work", "as"), ("i", "work", "at"), ("i", "work", "in"), ("i", "work", "for"), ("i", "run", "a"), ("i", "own", "a"), ("i", "earn"), ("i", "was", "born"), ("i", "belong", "to"), ("i", "come", "from"), ("i", "stay", "in"), ("lost", "my", "job"), ("i", "got", "married"), ("we", "are", "a"), ("we", "re", "a"), ("we", "have", "a"), ("being", "a"), ("being", "an"), ("someone", "like", "me"), ("people", "like", "me"), ("in", "my", "case"), ("in", "my", "situation"), ("my", "situation"), ("my", "circumstances"), ("for", "my", "family"), ("for", "my", "age"))


def _describes_self(words: List[str]) -> bool:
    if any(_contains(words, phrase) for phrase in _CIRCUMSTANCES):
        return True
    if len(words) > 2 and words[0] == "as" and words[1] in ("a", "an") and words[2] not in _GENERIC_ROLES:
        return True
    for i, word in enumerate(words):
        after = words[i + 1:]
        if word == "my" and after and after[0] in _LIFE_WORDS:
            return True
        if word == "me" and i > 0 and words[i - 1] == "for":
            if not any(w in _SERVICE_VERBS for w in words[max(0, i - 6):i - 1]):
                return True
        if i > 0 and words[i - 1] in _HYPOTHETICAL:
            continue
        if word == "i" and len(after) >= 3 and after[0] == "have" and after[1] in ("a", "an") and after[2] not in _HAVE_NOT:
            return True
        if word == "i" and len(after) >= 2 and after[0] in ("am", "m"):
            x = after[1]
            if x in ("a", "an", "the"):
                if len(after) >= 3 and after[2] not in _ARTICLE_FILLERS and after[2] not in _GENERIC_ROLES:
                    return True
            elif x.isdigit() or (not x.endswith("ing") and x not in _NOT_DESCRIPTION):
                return True
    return False


def _describes_caller(words: List[str]) -> bool:
    if _describes_self(words) or any(_contains(words, phrase) for phrase in _SELF_PHRASES):
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
    for index, word in enumerate(words):
        if word not in _POSSESSIVES:
            continue
        if any(near in _HELD_RECORDS for near in words[index + 1:index + 3]):
            return index
    return None


def _is_state_interrogative(words: List[str]) -> bool:
    return words[0] in _STATE_LEADS or "status" in words


# --- Turns whose answer must never be shared ------------------------------------------
# Kept word for word with the Node SDK (voice.js) and the server (cache/mod.rs
# `never_share`). Each group fails closed: a match means "answer fresh, never cache".

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
_EMAIL_ENDINGS = frozenset({"com", "in", "org", "net", "co", "io"})
_ACTION_VERBS = frozenset(
    {
        "cancel", "book", "reschedule", "change", "update", "delete", "remove", "send", "text",
        "email", "call", "connect", "transfer", "escalate", "refund", "replace", "exchange",
        "return", "speak", "talk", "process", "block", "unblock", "check", "track", "add",
        "apply", "upgrade", "downgrade", "activate", "deactivate", "close", "open", "resend",
    }
)
# A verb first is a request only when it acts on something the caller points at
# ("cancel my order", "send me the invoice"). A bare verb is search-style phrasing:
# "refund status for john", "send events to an endpoint".
_ACTION_OBJECTS = frozenset({"me", "my", "it", "this", "that", "us", "our", "the", "them"})
# After these leads, an action verb is a request for the agent to do something.
_ACTION_LEADS = (
    ("please",), ("can", "you"), ("could", "you"), ("will", "you"), ("would", "you"),
    ("i", "want", "to"), ("i", "d", "like", "to"), ("i", "would", "like", "to"),
    ("i", "need", "to"), ("let", "me"), ("i", "wanna"),
)
# Replies to the agent, not questions: a reply word first (or "okay" + a reply word),
# and no wh-question word anywhere.
_REPLY_LEADS = frozenset({"yes", "yeah", "yep", "yup", "no", "nope", "nah", "correct", "exactly", "sure"})
_SOFT_REPLY_LEADS = frozenset({"okay", "ok", "alright", "fine", "right"})
_REPLY_FOLLOWERS = frozenset({"go", "please", "thanks", "thank", "that"})
_WH_WORDS = frozenset({"how", "what", "when", "where", "which", "who", "why"})
_SINGLE_WORDS = frozenset(
    {
        # live data
        "today", "tonight", "currently", "outage", "queue",
        # memory of this call
        "remember",
        # dialogue and complaints
        "pardon", "louder", "slower", "slowly", "ridiculous", "frustrated", "frustrating",
        "angry", "upset", "worst", "terrible", "unacceptable", "disappointed",
        # steering
        "pretend", "ignore", "roleplay",
        # sensitive advice
        "pregnancy", "pregnant", "breastfeeding", "allergic", "allergy", "allergies",
        "medicine", "medication", "dosage", "doctor", "symptoms", "sue", "lawsuit",
        "lawyer", "legal", "invest", "investment",
        # abuse
        "stupid", "idiot", "useless", "dumb", "shit", "damn", "hell", "crap", "fuck",
        "fucking", "bullshit", "bloody",
        # identity checks
        "otp", "cvv",
        # Hinglish possessives and first person
        "mera", "meri", "mere", "maine", "mujhe", "hamara", "hamari",
        # handing over to a person, Hinglish "I am"
        "supervisor", "hoon", "hun",
    }
)
_PHRASES = (
    # self-introduction
    ("my", "name"), ("name", "s"), ("call", "me"), ("i", "m", "called"),
    # memory of this call
    ("did", "i", "tell"), ("did", "i", "say"), ("did", "i", "just"), ("i", "told", "you"),
    ("as", "i", "said"), ("i", "mentioned"), ("who", "i", "am"), ("have", "i"),
    # things the caller did
    ("i", "ordered"), ("i", "bought"), ("i", "paid"), ("i", "placed"), ("i", "received"),
    ("i", "purchased"), ("i", "returned"), ("i", "booked"), ("i", "cancelled"), ("i", "canceled"),
    ("i", "was", "charged"), ("i", "got", "charged"), ("i", "haven", "t"), ("i", "didn", "t"),
    ("charged", "twice"), ("double", "charged"),
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
    ("for", "this", "call"), ("for", "the", "rest"), ("tell", "everyone"), ("your", "rules"),
    ("your", "instructions"), ("previous", "instructions"), ("system", "prompt"),
    # sensitive advice
    ("safe", "during"), ("safe", "for", "kids"),
    # Indian-English and Hinglish introductions, personal fit, hand-over, steering
    ("this", "side"), ("bol", "raha"), ("bol", "rahi"), ("name", "you", "have"), ("have", "for", "me"), ("suit", "me"), ("suits", "me"), ("me", "best"), ("put", "me", "through"), ("transfer", "me"), ("connect", "me"), ("from", "here", "on"), ("call", "yourself"),
    # the caller's own purchases and payments
    ("did", "i", "order"), ("did", "i", "buy"), ("did", "i", "pay"), ("did", "i", "purchase"), ("did", "i", "get"), ("i", "ordered"), ("i", "bought"), ("i", "purchased"), ("i", "paid"), ("last", "time", "i"),
)
_DIGITS = re.compile(r"[0-9]{5,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]@[A-Za-z0-9-]")


def _never_share(text: str, words: List[str]) -> bool:
    """Whether a turn's answer must never be shared, whatever the rest of the rules say."""
    if any("ऀ" <= ch <= "ॿ" for ch in text):  # Devanagari: not supported yet, fail closed
        return True
    if _DIGITS.search(text) or _EMAIL.search(text):
        return True
    if "at" in words and "dot" in words and any(w in _EMAIL_ENDINGS for w in words):
        return True
    run = 0
    for word in words:
        run = run + 1 if word in _SPOKEN_DIGITS else 0
        if run >= 4:
            return True
    if any(w in _SINGLE_WORDS for w in words) or any(_contains(words, p) for p in _PHRASES):
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
    if len(words) > 1 and words[0] in _ACTION_VERBS and words[1] in _ACTION_OBJECTS:
        return True
    for index in range(len(words)):
        for lead in _ACTION_LEADS:
            end = index + len(lead)
            if tuple(words[index:end]) == lead and end < len(words) and words[end] in _ACTION_VERBS:
                return True
    if words and not any(w in _WH_WORDS for w in words):
        if words[0] in _REPLY_LEADS:
            return True
        if words[0] in _SOFT_REPLY_LEADS and len(words) > 1 and (
            words[1] in _REPLY_LEADS or words[1] in _REPLY_FOLLOWERS
        ):
            return True
    for index in range(len(words) - 2):
        # "how many points do i have", not "do i have to pay for returns"
        if tuple(words[index:index + 3]) == ("do", "i", "have") and (index + 3 >= len(words) or words[index + 3] != "to"):
            return True
    return False


def _is_personal(text: str) -> bool:
    words = _words(text)
    if _never_share(text, words) or _describes_caller(words):
        return True
    index = _owned_record_at(words)
    if index is None:
        return False
    if any(_contains(words, phrase) for phrase in _PROCEDURAL):
        return False
    if index > 0 and words[index - 1] in _OWNER_PREPOSITIONS:
        return _is_state_interrogative(words)
    return True


def _has_antecedent(before: List[str]) -> bool:
    return any(word not in _FUNCTION_WORDS and word not in _NON_REFERENTS for word in before)


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
        if not _has_antecedent(words[:index]):
            return True
    return False


def _is_context_dependent(text: str) -> bool:
    words = _words(text)
    if not words:
        return False
    if words[0] in _CONNECTIVES:
        return True
    if " ".join(words[:2]) in _CONNECTIVE_PAIRS:
        return True
    if words[0] in _ELLIPSIS_LEADS and not any(w in _CLAUSE_MARKERS for w in words[1:]):
        return True
    if any(_contains(words, phrase) for phrase in _FOLLOW_UP_PHRASES) or words[-1] in _FOLLOW_UP_ENDINGS:
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



# An answer that does not answer (a question back, "I'm not sure", a refusal) is spoken but never saved: cached, it becomes every later caller's answer, and it keeps rephrasings of the question from matching a real answer.
_NON_ANSWER_PHRASES = (
    "could you let me know",
    "could you tell me",
    "can you tell me",
    "could you clarify",
    "can you clarify",
    "could you specify",
    "can you specify",
    "could you provide",
    "can you provide",
    "please clarify",
    "please specify",
    "please provide",
    "let me know the ",
    "let me know which",
    "let me know what",
    "let me know your",
    "what do you mean",
    "which one do you mean",
    "i'm not sure",
    "i am not sure",
    "i don't know",
    "i do not know",
    "i can't help",
    "i cannot help",
    "i can't answer",
    "i cannot answer",
    "i'm unable",
    "i am unable",
    "i don't have access",
    "i do not have access",
    "i don't have information",
    "i do not have information",
    "need more information",
    "need more details",
)
_SENTENCE = re.compile(r"[^.!?]+[.!?]*")


def _is_non_answer(answer: str) -> bool:
    text = " ".join((answer or "").lower().replace("\u2019", "'").split())
    sentences = [s.strip() for s in _SENTENCE.findall(text) if s.strip(" .!?")]
    if not sentences:
        return False
    if all(s.endswith("?") for s in sentences):
        return True
    # Only when it leads: "Costs vary by destination. Please provide the address." still answers.
    return any(phrase in sentences[0] for phrase in _NON_ANSWER_PHRASES)


def is_personal(text: str) -> bool:
    """Whether a turn is about the caller (their records, who they are, what suits them).

    Its answer is theirs alone: never looked up in, nor saved to, the shared cache.
    """
    return _is_personal(text)


def is_context_dependent(text: str) -> bool:
    """Whether a turn only means something after the previous one ("how long does it take?")."""
    return _is_context_dependent(text)


def is_non_answer(answer: str) -> bool:
    """Whether a model answer does not answer: only questions back, or it leads with
    a clarification or "I'm not sure". Such an answer is spoken, never saved."""
    return _is_non_answer(answer)


__all__ = ["is_personal", "is_context_dependent", "is_non_answer"]
