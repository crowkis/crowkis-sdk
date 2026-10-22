"""Stats: a voice session's counters, kept in one place."""

from __future__ import annotations

import collections
import threading
from enum import Enum
from typing import Any, Dict


class Counter(str, Enum):
    """The counters a voice session keeps; each value is the session attribute ``stats()`` reads."""

    SERVED = "served"
    FILLED = "filled"
    INFERRED = "inferred"
    REFUSED_SHORT = "refused_short"
    REFUSED_PRIVATE = "refused_private"
    UNCACHEABLE_PERSONAL = "uncacheable_personal"
    OVER_BUDGET = "over_budget"
    BARGE_INS = "barge_ins"
    LOOKUP_ERRORS = "lookup_errors"
    LEARN_ERRORS = "learn_errors"
    SLOW_WRITES = "slow_writes"
    DIFFERENT_QUESTION = "different_question"
    NOT_SHAREABLE = "not_shareable"
    HELD_COMMITMENTS = "held_commitments"
    UNSPEAKABLE = "unspeakable"
    EMPTY_ANSWERS = "empty_answers"
    AUDIO_UNAVAILABLE = "audio_unavailable"


class Stats:
    """The session's counters and how often each rule decided. ``add`` holds a lock, as counters a
    background write worker and a turn may both update did before; plain reads and writes go
    through ``CounterField`` on the session, as they always did."""

    def __init__(self) -> None:
        self._counts: Dict[Counter, int] = {counter: 0 for counter in Counter}
        self.rules: collections.Counter = collections.Counter()
        self._lock = threading.Lock()

    def get(self, counter: Counter) -> int:
        return self._counts[counter]

    def set(self, counter: Counter, value: int) -> None:
        self._counts[counter] = value

    def add(self, counter: Counter, amount: int = 1) -> None:
        """Add to a counter under the lock (a write worker and a turn may both count)."""
        with self._lock:
            self._counts[Counter(counter)] += amount

    def count_rule(self, rule: str) -> None:
        """One more turn or answer that ``rule`` decided."""
        self.rules[rule] += 1

    def rule_counts(self) -> Dict[str, int]:
        return dict(sorted(self.rules.items()))


class CounterField:
    """A session attribute (``session.filled``) that reads and writes its counter in the session's
    ``_stats``, so the public counters keep their names, values and ``+= 1`` behaviour."""

    def __init__(self, counter: Counter) -> None:
        self._counter = counter

    def __get__(self, owner: Any, owner_type: Any = None) -> Any:
        if owner is None:
            return self
        return owner._stats.get(self._counter)

    def __set__(self, owner: Any, value: int) -> None:
        owner._stats.set(self._counter, value)
