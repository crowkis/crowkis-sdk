"""The word checks Chat's frame rules use: tokens and stems, words any question may add, and the
patterns of an identifying detail. Moved unchanged from verify.py in v4 P3; verify.py re-exports them."""

from __future__ import annotations

import re
from typing import List

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
# Facts that tailor an answer to the caller: what they have, how old, where and when.
# Facts that tailor an answer. What the user told (a place, a time, a number) is in `stated`, from
# fixed code; a place or time in an earlier shared question is only its topic ("France").
_TOLD_TYPES = frozenset({"condition"})
_NUMWORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
             "eight": "8", "nine": "9", "ten": "10"}
_UNITS = r"(rupees?|rs|inr|dollars?|usd|items?|people|persons?|days?|weeks?|months?|years?|hours?|kg|gb|inch(es)?|%)"
_EMAIL = re.compile(r"\S+@\S+|\bat\s+(gmail|yahoo|hotmail|outlook)\b", re.I)
_PHONE = re.compile(r"\b\d{10}\b|\(\d{3}\)\s*\d{3}-\d{4}")
_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){4,}")


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


# Neutral words a stand-alone rewrite may add although the user did not say them ("how many people
# live there" -> "population"). Exact words, never stems ("tim" is not "time"), and none that could
# change what is asked ("avoid", "best", "cheapest", "safe") or tailor it ("vegan", "child").
_QUESTION_WORDS = frozenset("population distance duration step steps process amount number list requirements difference differences type types kind kinds".split())
_REFERRING = frozenset("it its they them their there here this that those these he she him his her".split())
_CONTRACTION = frozenset("s t d m re ll ve".split())  # "what's" -> "what", "s": "s" names nothing
_CLAUSE_START = frozenset("i we you he she they it my our your his her their me".split())
# Words that name a kind of fact, not which one: "allergies" alone does not carry "allergic to
# penicillin". A heuristic list; a fact made only of them ("I'm allergic.") still counts them.
# Acronyms of things, never of a person ("SIM porting", "a UPI refund"): a capitalised word in a shared
# question that is one of these is no name (v4, misfire B05).
_COMMON_ACRONYMS = frozenset(
    {"sim", "esim", "upi", "otp", "pin", "emi", "kyc", "gst", "atm", "usb", "api", "faq", "pdf", "sms", "mms", "gdpr",
     "icu", "opd", "ac", "tv", "wifi", "gps", "id", "sso", "csv", "vpn", "url", "ssd", "ram", "cpu", "nfc", "qr",
     "pnr", "ifsc", "neft", "rtgs", "imps", "cod", "eta", "ev", "abs"}
)
_GENERIC_FACT = frozenset(_stem(w) for w in "allergy allergic allergies intolerant intolerance sensitive sensitivity condition disease illness problem issue".split())


def _looks_identifying(question: str) -> bool:
    if _EMAIL.search(question) or _PHONE.search(question):
        return True
    low = question.lower()
    for match in _LONG_DIGITS.finditer(low):
        if not re.match(r"\s*" + _UNITS, low[match.end(): match.end() + 12]):
            return True  # a long number that is not a quantity: an order ID, account, phone...
    return False


_DAYS = "monday tuesday wednesday thursday friday saturday sunday".split()
_CALENDAR = frozenset("january february march april may june july august september october november december".split()
                      + _DAYS + [d + "s" for d in _DAYS])
