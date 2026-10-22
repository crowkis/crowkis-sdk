"""Verdict: one rule's objection to a turn, a cached answer or a model's answer."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Tuple


@dataclass(frozen=True)
class Verdict:
    """What a rule says when it objects.

    ``rule`` names the rule (in decisions, logs and ``stats()``), ``reason`` says why in words,
    ``counts`` are the session counters it adds to (``runtime.stats.Counter``),
    ``outcome`` is, for a save rule, what happened to the answer ("kept", "private", ...), and
    ``route`` is, for a rule that decides alone, where the turn goes ("urgent", "task", "filler"),
    and ``answer`` is what to say at once when the rule answers the turn itself (a filler).
    """

    rule: str
    reason: str
    counts: Tuple[Any, ...] = ()
    outcome: Optional[str] = None
    route: Optional[str] = None
    answer: Optional[str] = None
