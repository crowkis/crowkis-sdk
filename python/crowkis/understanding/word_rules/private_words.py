"""Private words: tokens and stems, the names, numbers and capitalised words that may identify a caller, the
masking of a stated turn, and the answer patterns the save rules look for."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, List, Optional, Set

from ..model.frame import TurnFrame
from .text import _proper_nouns, _words

# Words any question may use without them appearing in the turn: grammar, question words and
# ordinary request verbs. Not a list about meaning; it never decides kind or privacy.
_FUNCTION = frozenset("""a an the and or but if of to in on at for from by with about into over under after before
during than then so as is are was were be been being am do does did done doing have has had having can could will
would shall should may might must i you we they it its this that these those there here what which who whom whose
when where why how much many long often any some each every all no not yes my your our their me us them per same
other another own just only also more most less least very please get got getting give make take need want use used
using apply applying offer offers offered available availability allowed allow include includes included work works
working cost costs charge charged charges price pricing fee fees option options way ways happen happens like
differ different one two three four five six seven eight nine ten first second third time times day days
tell find found look looking show give know serve serves served recommend suggest
someone somebody anyone person people year years old aged""".split())

_WORD = re.compile(r"[a-z0-9]+")
_NUMWORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
             "eight": "8", "nine": "9", "ten": "10"}


def _toks(text: str) -> List[str]:
    return [_NUMWORDS.get(w, w) for w in _WORD.findall((text or "").lower())]


def _stem(word: str) -> str:
    """Crude, symmetric word-form normaliser: expires/expire, removing/remove, qualifies/qualify."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    if len(word) > 6 and word.endswith("ic"):  # allergic/allergy, diabetic/diabetes; not topic, music
        word = word[:-2]
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    if len(word) > 3 and word.endswith(("y", "i")):
        word = word[:-1]
    return word


_DAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
_CALENDAR = frozenset("january february march april may june july august september october november december".split()
                      + _DAYS + [d + "s" for d in _DAYS])


_ANSWER_EMAIL = re.compile(r"\S+@\S+")
_ANSWER_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){5,}")
_ACTION_CLAIM = re.compile(
    r"\b(i\s*(have|['’]ve)|i\s+just|we\s*(have|['’]ve))\s+(cancel+ed|booked|refunded|processed|changed|updated|"
    r"reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\b"
    r"|\bi(\s+will|['’]ll)\s+(add|cancel|book|send|schedule|reserve|place|remind|order)\b"
    r"|\b(has|have)\s+been\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted|added)\b", re.I)


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
    for named in _ANSWER_EMAIL.findall(text) + _ANSWER_LONG_DIGITS.findall(text):
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


def _private_words(text: str, frame: Optional[TurnFrame] = None) -> List[str]:
    """Everything in a turn that may identify the caller: its names, any number, any capitalised
    word. Broad on purpose; it only ever refuses a shared answer, so a wrong guess costs a hit."""
    found = {w for w in _words(text) if any(c.isdecimal() for c in w)} | _proper_nouns(text)
    return sorted(found | set(_names(text, frame)))


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


