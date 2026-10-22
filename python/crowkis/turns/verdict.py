"""Verdict: one rule's objection to a turn, a cached answer or a model's answer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass(frozen=True)
class Verdict:
    """What a rule says when it objects.

    ``rule`` names the rule (in decisions, logs and ``stats()``), ``reason`` says why in words,
    ``counts`` are the session counters it adds to (the names ``stats()`` reports today), and
    ``outcome`` is, for a save rule, what happened to the answer ("kept", "private", ...).
    """

    rule: str
    reason: str
    counts: Tuple[str, ...] = ()
    outcome: Optional[str] = None
