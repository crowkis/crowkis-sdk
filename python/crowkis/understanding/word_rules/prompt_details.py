"""System-prompt details: a caller's details a prompt gives, and answers that repeat them."""

from __future__ import annotations

import collections
import re
import threading
from typing import List, Optional

from .text import (  # noqa: F401
    _FUNCTION_WORDS,
    _TOKEN,
    _is_decimal_word,
    _numbers,
    _words,
)
from .phrases import (  # noqa: F401
    _EMAIL_ENDINGS,
)


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
