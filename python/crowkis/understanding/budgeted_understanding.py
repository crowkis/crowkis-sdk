"""BudgetedUnderstanding: a plugged-in classifier and rewriter, inside their error boundary and budget."""

from __future__ import annotations

import concurrent.futures
import logging
import threading
from typing import Callable, Optional, Sequence, Tuple

from ..runtime.stats import Counter
from .slots import Classifier, Reading, Rewriter
from .word_rule_classifier import WordRuleClassifier

MS_PER_SECOND = 1000.0
# A session's model calls still running past their budget hold at most this many shared workers; while
# they do, its turns go straight to the word rules, so one hung model never starves other sessions.
MAX_IN_FLIGHT = 4

_LOG = logging.getLogger("crowkis")


class BudgetedReading:
    """A turn's reading with the rewrite made inside the same budget (None: the caller's words)."""

    def __init__(self, reading: Reading, rewritten: Optional[str]) -> None:
        self.reading = reading
        self.rewritten = rewritten

    @property
    def is_personal(self) -> bool:
        return self.reading.is_personal

    @property
    def is_context_dependent(self) -> bool:
        return self.reading.is_context_dependent

    @property
    def frame(self):
        return getattr(self.reading, "frame", None)


class BudgetedUnderstanding:
    """Decorator over a classifier and a rewriter that fills both slots: the model reads and rewrites a
    turn inside ``budget_ms`` (None: no deadline). This is the one place understanding fails open: a
    late or failed model means the word rules read the turn and it keeps the caller's words, never
    "share anyway". Each such turn is counted (``understand_timeouts``, ``understand_errors``) and
    logged without its words."""

    def __init__(self, classifier: Classifier, rewriter: Rewriter, *, budget_ms: Optional[float],
                 pool: concurrent.futures.Executor, count: Callable[[Counter], None],
                 fallback: Optional[Classifier] = None) -> None:
        self._classifier = classifier
        self._rewriter = rewriter
        self._budget_ms = budget_ms
        self._pool = pool
        self._count = count
        self._fallback = fallback if fallback is not None else WordRuleClassifier()
        self._in_flight = threading.BoundedSemaphore(MAX_IN_FLIGHT)

    def classify(self, text: str, facts: Sequence[str] = ()) -> BudgetedReading:
        """The model's reading and rewrite, or the word rules' reading when the model is late or fails."""
        try:
            reading, rewritten = self._understand_in_time(text, facts)
        except concurrent.futures.TimeoutError:
            return self._fall_back(text, Counter.UNDERSTAND_TIMEOUTS, f"passed the {self._budget_ms}ms budget")
        except Exception as error:  # noqa: BLE001 — a broken model must never end a call
            return self._fall_back(text, Counter.UNDERSTAND_ERRORS, f"failed ({type(error).__name__})")
        return BudgetedReading(reading, rewritten)

    def rewrite(self, text: str, reading: BudgetedReading) -> Optional[str]:
        """The rewrite made with the reading (classify() ran both)."""
        return reading.rewritten

    def _understand_in_time(self, text: str, facts: Sequence[str]) -> Tuple[Reading, Optional[str]]:
        if self._budget_ms is None:
            return self._understand(text, facts)
        if not self._in_flight.acquire(blocking=False):
            raise concurrent.futures.TimeoutError
        future = self._pool.submit(self._understand, text, facts)
        future.add_done_callback(lambda _: self._in_flight.release())
        try:
            return future.result(timeout=self._budget_ms / MS_PER_SECOND)
        except concurrent.futures.TimeoutError:
            future.cancel()  # not started yet: it never will
            raise

    def _understand(self, text: str, facts: Sequence[str]) -> Tuple[Reading, Optional[str]]:
        reading = self._classifier.classify(text, facts)
        return reading, self._rewriter.rewrite(text, reading)

    def _fall_back(self, text: str, counter: Counter, why: str) -> BudgetedReading:
        self._count(counter)
        _LOG.warning("crowkis understanding %s; the word rules read this turn", why)
        return BudgetedReading(self._fallback.classify(text), None)
