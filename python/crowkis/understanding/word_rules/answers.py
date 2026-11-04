"""Answers: spoken or screen text, non-answers, answer shapes, questions about other things."""

from __future__ import annotations

import collections
import re
import threading
from typing import Dict, List, Optional

from .text import _content_words, _FUNCTION_WORDS, _TOKEN, _is_decimal_word, _numbers, _words, _EMAIL_ENDINGS

_SLOT = re.compile(r"\{([^{}\s]+)\}")


# Text written for a screen: a link, code, or markup a voice would read out.
_UNSPEAKABLE = re.compile(
    r"https?://|www\.|`|\]\(|\*\*|^\s*(?:#{1,6}\s|\|)", re.MULTILINE | re.IGNORECASE
)


def _speakable(text: str) -> bool:
    return not _UNSPEAKABLE.search(text or "")


def _different_specifics(asked: str, stored: str) -> bool:
    """Two questions about different things: each has content words the other does
    not ("on Saturday" / "on Sunday", "the city museum" / "the riverside greenhouse").
    A rewording only adds or drops words on one side ("when are you open" / "what
    are your opening hours"), or changes how it asks ("can I" / "do I")."""
    a, s = _content_words(asked), _content_words(stored)
    return bool(a - s) and bool(s - a)


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
    "i do not have information", "i don't have that information", "i do not have that information", "i don't have the information", "i do not have the information", "i don't have any information", "i do not have any information", "i need to know", "please let me know", "need more information", "need more details",
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
