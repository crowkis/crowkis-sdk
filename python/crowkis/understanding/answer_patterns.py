"""Patterns Chat's save rules look for in an answer: an email, a long digit run (an ID, an account),
a claim that something was done. Moved unchanged from session.py in v4 P3; session.py re-imports them."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"\S+@\S+")
_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){5,}")
_ACTION_CLAIM = re.compile(
    r"\b(i\s*(have|'ve)|i\s+just|we\s*(have|'ve))\s+(cancel+ed|booked|refunded|processed|changed|updated|"
    r"reset|sent|placed|scheduled|reserved|blocked|deleted|removed|added|issued)\b"
    r"|\b(has|have)\s+been\s+(cancel+ed|booked|refunded|processed|reserved|blocked|deleted)\b", re.I)
