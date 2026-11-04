"""The understanding slots (what a classifier and a rewriter give a turn) and how a voice session fills
them: the word rules by default, no rewrite, a text-only classifier adapter, and the budget and fallback
around a plugged-in model."""

from __future__ import annotations

import concurrent.futures
import inspect
import logging
import threading
from functools import cached_property
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, Sequence, Tuple

from ..runtime.stats import Counter
from .word_rules.follow_up import _is_context_dependent
from .word_rules.personal import _is_personal

if TYPE_CHECKING:
    from .model.frame import TurnFrame


class Reading(Protocol):
    """What a classifier makes of one turn's words."""

    @property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""

    @property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it."""

    @property
    def frame(self) -> "Optional[TurnFrame]":
        """The model's frame of the turn, or None for a reading without one (the word rules)."""


class Classifier(Protocol):
    """Reads a turn (WordRuleClassifier today; an LLM or ONNX model later). ``facts`` are the
    call's remembered facts ("condition: car hit") and the turns in which the caller told it something."""

    def classify(self, text: str, facts: Sequence[str] = ()) -> Reading:
        """What this turn is."""


class Rewriter(Protocol):
    """Turns a follow-up into a stand-alone question (NoRewrite today)."""

    def rewrite(self, text: str, reading: Reading) -> Optional[str]:
        """The stand-alone question, or None to key the turn on the caller's words."""


class WordReading:
    """What the word rules make of one turn's words. Each reading is worked out once, when a
    rule first needs it."""

    # The word rules make no frame.
    frame = None

    def __init__(self, text: str) -> None:
        self.text = text

    @cached_property
    def is_personal(self) -> bool:
        """About the caller's own records, or otherwise never shared."""
        return _is_personal(self.text)

    @cached_property
    def is_context_dependent(self) -> bool:
        """Only means something next to the turn before it."""
        return _is_context_dependent(self.text)


class WordRuleClassifier:
    """The classifier a voice session uses when no understander is plugged in: the fixed word
    rules, so nothing changes without opt-in."""

    def classify(self, text: str, facts: Sequence[str] = ()) -> WordReading:
        return WordReading(text)


class NoRewrite:
    """Null Object for the rewriter slot: no stand-alone question, so a turn's cache key stays
    the caller's own words (or the chain a follow-up leans on), as today."""

    def rewrite(self, text: str, reading: Any) -> Optional[str]:
        return None


# The arguments the slot passes: the turn and the call's facts.
SLOT_ARGUMENTS = 2


class TextOnlyClassifier:
    """Adapter: a classifier that reads the turn alone (the P2-P4 protocol, ``classify(text)``) keeps
    working now that the slot also passes the call's facts; it simply does not get them."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @classmethod
    def fit(cls, classifier: Any) -> Classifier:
        """``classifier`` itself when it takes the facts, else this adapter around it."""
        try:
            inspect.signature(classifier.classify).bind(*(None,) * SLOT_ARGUMENTS)
        except TypeError:
            return cls(classifier)
        except ValueError:  # no signature to read (a builtin): pass the facts and let it say
            return classifier
        return classifier

    def classify(self, text: str, facts: Sequence[str] = ()) -> Reading:
        return self._inner.classify(text)


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
                 pool: concurrent.futures.Executor, count: Callable[[Counter], None]) -> None:
        self._classifier = classifier
        self._rewriter = rewriter
        self._budget_ms = budget_ms
        self._pool = pool
        self._count = count
        self._fallback = WordRuleClassifier()
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
