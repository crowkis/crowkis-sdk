"""Word and phrase tables more than one theme of the word rules reads."""

from __future__ import annotations

import re

from .text import (  # noqa: F401
    _MATTERS,
    _RELATIONS,
    _first_words,
)


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
