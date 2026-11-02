"""What a chat turn tells and gives away: the names in it, the details the user told, its private words,
and a reply masked before it is kept. Moved unchanged from session.py in v4 P3; session.py re-exports them."""

from __future__ import annotations

from .turn_frame import TurnFrame
from .answer_patterns import _EMAIL, _LONG_DIGITS
from .frame_words import _CALENDAR
from .frame_words import _FUNCTION
from .word_rules import _proper_nouns, _words
from typing import Any, List, Optional, Set, Tuple
import re
import string
import unicodedata


# Phrases a name follows ("my name is sarah", "call me raj", "this is priya"). "I'm" is not
# one here: "I'm allergic" is a fact, not a name, and the shared question may carry it.
_NAME_LEADS = (("name", "is"), ("call", "me"), ("this", "is"))


# "I'm Sarah" / "i am sarah, ...": the word after is a name when capitalised, or when the phrase ends
# with it; in a turn telling a fact only when "and" or a comma follows ("I'm diabetic." is the fact).
_SELF_INTRO = re.compile(r"\b[Ii](?:['’]m| am|m)\s+([^\W\d_]+)(\s*(?:[,.!?;]|$)|\s+(?:and|from|here|calling|speaking)\b)?")


# Words a person's name follows ("my colleague JOSE", "my son Arjun", "my teacher Mr Smith"): after
# my/our/his/her/their/your, the next capitalised word is a name whatever the model tagged it as.
_RELATIONS = frozenset("colleague coworker friend son daughter wife husband partner mother mom mum father dad brother sister boss manager kid child baby grandma grandpa grandmother grandfather uncle aunt cousin neighbour neighbor roommate girlfriend boyfriend fiance fiancee teacher doctor client customer".split())


_POSSESSIVE = frozenset("my our his her their your s".split())  # "s": "my wife's sister PRIYA"


_TITLES = frozenset("mr mrs ms miss dr sir madam".split())


def _names(text: str, frame: Optional[TurnFrame] = None, fact: bool = True) -> List[str]:
    """What names the caller in a turn: emails, long numbers, a name after "my name is", what the
    understanding model tagged as identifying, and, in a turn that is not telling a fact, any name
    it gives ("hi i'm sarah"). A fact turn keeps its words ("I'm allergic"): the question carries them."""
    words = _words(text)
    found = set()
    for named in _EMAIL.findall(text) + _LONG_DIGITS.findall(text):
        found.update(_words(named))
    for i in range(len(words)):
        for lead in _NAME_LEADS:
            end = i + len(lead)
            if tuple(words[i:end]) == lead and end < len(words) and words[end] not in _FUNCTION:
                found.add(words[end])
    for t in frame.identifying_texts if frame else ():
        found.update(_words(t))
    tokens = re.findall(r"[^\W\d_]+", text)
    for i in range(1, len(tokens) - 1):
        if tokens[i].lower() in _RELATIONS and tokens[i - 1].lower() in _POSSESSIVE:
            nxt = tokens[i + 1]
            # "Mr Smith", "O'Brien": the name is the word after the title or the one-letter part.
            for word in tokens[i + 1:i + 3] if nxt.lower() in _TITLES or len(nxt) == 1 else [nxt]:
                low = word.lower()
                if word != "I" and low not in _FUNCTION and low not in _CALENDAR and \
                        any(unicodedata.category(c) in ("Lu", "Lt") for c in word):
                    found.add(low)
    for m in _SELF_INTRO.finditer(text):
        word = m.group(1)
        closer = None if m.group(2) is None else m.group(2).strip()
        if word.lower() not in _FUNCTION and (word[0].isupper() or (closer is not None and (not fact or closer in (",", "and")))):
            found.add(word.lower())
    return sorted(found)


def _told(text: str, frame: TurnFrame) -> Tuple[Set[str], List[str]]:
    """A turn telling a fact, in two parts: what names the caller (never kept, never in a shared
    question) and the details a shared question must carry: a short number, a month or day, a
    place or thing the understanding model tagged ("3", "December", "Goa"). Any other capitalised
    word, a sentence's first included ("Priya and I..."), is a name AND a detail: a question can
    never both carry it and leave it out, so a chat whose model tagged nothing stays private."""
    words = _words(text)
    named = set(_names(text, frame))
    tagged = {w for e in frame.entities if not e.identifying and e.type != "other_person" for w in _words(e.text)}
    capitalised = {w.lower() for w in re.findall(r"[^\W\d_]+", text) if w[0].isupper() and w != "I"} - _FUNCTION
    untagged = {w for w in capitalised if w not in _CALENDAR and w not in tagged}
    named |= untagged | {w for w in words if any(c.isdecimal() for c in w) and len(w) > 3}
    details = ({w for w in words if any(c.isdecimal() for c in w)} | capitalised) - named
    return named, sorted(details | untagged)


def _private_words(text: str, frame: Optional[TurnFrame] = None) -> List[str]:
    """Everything in a turn that may identify the caller: its names, any number, any capitalised
    word. Broad on purpose; it only ever refuses a shared answer, so a wrong guess costs a hit."""
    found = {w for w in _words(text) if any(c.isdecimal() for c in w)} | _proper_nouns(text)
    return sorted(found | set(_names(text, frame)))


_TRIM = string.punctuation + string.whitespace


# A reply to a private turn is kept between turns only to follow the conversation: names,
# emails and numbers in it are masked first (any word with a capital, a digit, or a letter of a
# script without case).
_REPLY_WORD = re.compile(r"\S+@\S+|\w+")


_MASKED = frozenset(("Lu", "Lt", "Lo", "Nd", "Nl", "No"))


def _masked(reply: Any) -> str:
    return _REPLY_WORD.sub(lambda m: "_" if "@" in m.group() or any(
        unicodedata.category(c) in _MASKED for c in m.group()) else m.group(), str(reply or ""))


def _unnamed(text: str, private: Set[str]) -> str:
    """A stated turn as the voice classifier is sent it: masked as a reply is, and any word a private
    turn of the call held ("sharma") masked too."""
    return re.sub(r"\w+", lambda m: "_" if m.group().lower() in private else m.group(), _masked(text))


def _norm(text: str) -> str:
    """A filler trigger or a turn, normalised for matching: lower case, no edge punctuation, single spaces."""
    return " ".join((text or "").lower().strip(_TRIM).split())
