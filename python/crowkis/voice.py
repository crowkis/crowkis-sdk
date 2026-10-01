from __future__ import annotations

import concurrent.futures
import re
import string
import threading
import time
from typing import Callable, Dict, List, Optional

from .agent import Agent

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


def _describes_caller(words: List[str]) -> bool:
    if any(_contains(words, phrase) for phrase in _SELF_PHRASES):
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


_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="crowkis-voice")


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

    @property
    def served_from_cache(self) -> bool:
        return self.action == "serve"

    @property
    def served_from_filler(self) -> bool:
        return self.action == "filler"

    @property
    def needs_model(self) -> bool:
        return self.action == "infer"

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
    ) -> None:
        if not 0.0 <= serve_above <= 1.0:
            raise ValueError(f"serve_above must be in 0..1, got {serve_above}")
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
        self.serve_above = serve_above
        self.min_words = min_words
        self.synthesise = synthesise
        self.ttl = ttl
        self.latency_budget_ms = latency_budget_ms
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
        self._fillers: Dict[str, str] = {}
        self._open = False
        self._cancelled = False
        self._turn_mark = 0
        self._cacheable = False
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
        decision = self._decide(caller_said)
        self._cacheable = False
        if decision.needs_model:
            decision.messages, decision.cacheable = self._model_messages(caller_said)
            self._cacheable = decision.cacheable
        return decision

    def _model_messages(self, caller_said: str):
        """What the model should read to answer this turn, and whether that answer may be cached.

        A shared answer is only safe when the model saw nothing but the cache key:
        the question, and for a follow-up the question before it. Nothing else the
        caller said (a name, a plan, "pretend refunds are unlimited") can then end
        up inside it. Personal turns get the whole call and are never shared.
        """
        text = (caller_said or "").strip()
        if len(text.split()) < self.min_words or _is_personal(text):
            return None, False
        if not _is_context_dependent(text):
            return [{"role": "user", "content": caller_said}], True
        prior = self._prior_user()
        if prior is None or _is_personal(prior):
            return None, False
        return [{"role": "user", "content": prior}, {"role": "user", "content": caller_said}], True

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
            return TurnDecision(
                "filler",
                text=filler,
                audio=self._voiced(filler),
                confidence=1.0,
                reason="registered filler, answered without a lookup or a model",
            )

        if len(text.split()) < self.min_words:
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

        started = time.monotonic()
        lookup = lambda: self.agent.ask(  # noqa: E731
            keyed,
            serve_above=self.serve_above,
            cheap_above=min(0.60, self.serve_above),
            template=personal,
            threshold=_CONTEXT_BOUND_THRESHOLD if context_bound else None,
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

        self.served += 1
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": answer})
        return TurnDecision(
            "serve",
            text=answer,
            audio=self._voiced(answer, cacheable=not personal),
            confidence=hit["confidence"],
            reason="confident cache hit",
        )

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
        text to speak, from the cache or from the model.
        """
        decision = self.decide(caller_said)
        if not decision.needs_model:
            return decision
        messages = decision.messages
        if messages is None:
            messages = self.injections() + [{"role": "user", "content": caller_said}]
        if system:
            messages = [{"role": "system", "content": system}] + messages
        decision.text = llm(messages)
        self._record_model_turn(caller_said, decision.text)
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
        if self._cacheable:
            self.not_shareable += 1
        self._cacheable = False

    def _record_model_turn(self, caller_said: str, model_said: str) -> None:
        """Record the model's answer to the turn decide() last handled, and cache it if allowed.

        Only an answer written from ``decision.messages`` reaches this, so it is shared
        exactly when decide() said it may be. Never raises: a refused write (security
        pipeline, rate limit, cache down) must not end a call.
        """
        if self._cancelled:
            return
        self._open = False
        text = (caller_said or "").strip()
        keyed = self._context_key(caller_said, text)
        cacheable, self._cacheable = self._cacheable, False
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": model_said})
        if not (model_said and model_said.strip()) or keyed is None:
            return
        try:
            if _is_personal(text):
                self._learn_personal(keyed, model_said)
            elif not cacheable or _leaks(model_said, self.values):
                self.not_shareable += 1
            else:
                self.agent.learn(keyed, model_said, ttl=self.ttl)
        except Exception:  # noqa: BLE001 — see docstring
            self.learn_errors += 1

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
            "cache_hit_pct": pct(self.served),
            "filler_hit_pct": pct(self.filled),
            "model_calls_avoided_pct": pct(self.served + self.filled),
        }

    def _prior_user(self) -> Optional[str]:
        for turn in reversed(self.transcript):
            if turn["role"] == "user":
                return turn["content"]
        return None

    def _context_key(self, caller_said: str, text: str) -> Optional[str]:
        if not _is_context_dependent(text):
            return caller_said
        prior = self._prior_user()
        if prior is None:
            return None
        return f"{prior} || {caller_said}"

    def _learn_personal(self, keyed: str, model_said: str) -> None:
        shaped = _abstract(model_said, self.values)
        if (
            self.values
            and _SLOT.search(shaped)
            and not _leaks(shaped, self.values)
        ):
            self.agent.learn(keyed, shaped, ttl=self.ttl, template=True)
            return
        self.uncacheable_personal += 1

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        if self.synthesise is None:
            return None
        if not cacheable:
            return self.synthesise(answer)
        return self.agent.speak(answer, self.synthesise, voice=self.voice, ttl=self.ttl)


__all__ = ["VoiceSession", "TurnDecision"]
