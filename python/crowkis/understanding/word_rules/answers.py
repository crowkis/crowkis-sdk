"""Answers: spoken or screen text, non-answers, answer shapes, questions about other things."""

from __future__ import annotations

import re
from typing import Dict, Optional

from .text import (  # noqa: F401
    _content_words,
)


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
