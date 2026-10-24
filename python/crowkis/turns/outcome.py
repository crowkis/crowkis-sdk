"""Outcome: what happened to a model's answer; RecordedOutcome: an outcome as record() reports it."""

from __future__ import annotations

from enum import Enum
from typing import Optional


class Outcome(str, Enum):
    """The words callers see for an answer: ``decision.not_stored`` and the save rule's outcome on voice,
    Chat's outcomes and its "answer" events. A ``str`` enum, so each one compares, hashes, prints and
    serialises as its word."""

    SAVED = "saved"
    TEMPLATE = "template"
    KEPT = "kept"
    PRIVATE = "private"
    NON_ANSWER = "non_answer"
    NOT_SAVED = "not_saved"
    INTERRUPTED = "interrupted"
    NOT_SHARED = "not_shared"
    CANCELLED = "cancelled"
    STALE = "stale"
    SLOW_WRITE = "slow_write"
    REFUSED = "refused"

    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)

    def because(self, why: str) -> str:
        """Chat's form of this outcome with its reason: ``"refused:<why>"``."""
        return f"{self.value}:{why}"


class RecordedOutcome(str):
    """An ``Outcome`` as voice's record() reports it: the word, plus ``why`` an answer was not stored
    and the ``rule`` that decided it. A ``str``, because callers (the adapters, ``decision.stored``)
    compare it with the word and put it in reports."""

    why: str
    rule: Optional[str]

    def __new__(cls, outcome: Outcome, why: str = "", rule: Optional[str] = None) -> "RecordedOutcome":
        recorded = super().__new__(cls, str(outcome))
        recorded.why = why
        recorded.rule = rule
        return recorded
