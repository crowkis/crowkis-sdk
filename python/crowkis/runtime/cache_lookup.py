"""CacheLookup: the cache's answer to a turn, inside the call's latency budget."""

from __future__ import annotations

import concurrent.futures
import time
from typing import Any, Callable, Dict, Optional, Tuple, Union

from ..turns.verdict import Verdict
from .stats import Counter

MS_PER_SECOND = 1000.0
# The counters a lookup that failed open adds to: a voice session's by default.
DEADLINE_COUNTS = (Counter.OVER_BUDGET, Counter.INFERRED)
UNAVAILABLE_COUNTS = (Counter.LOOKUP_ERRORS, Counter.INFERRED)


class CacheLookup:
    """The one place a lookup fails open: a hard deadline (a slow or hung cache never holds a live
    call past its budget, and a hit that comes back late is refused), and an unreachable cache
    means the model answers. Returns the hit and, when the model must answer instead, a Verdict
    (LookupDeadline or CacheUnavailable). ``budget_ms`` is the call's budget at the time of the
    lookup; None waits as long as the cache takes. ``deadline_counts`` / ``unavailable_counts`` are the
    counters each verdict adds to (the channel's names)."""

    def __init__(self, pool: concurrent.futures.Executor, *, refuse_late_hits: bool = True,
                 deadline_counts: Tuple[Union[Counter, str], ...] = DEADLINE_COUNTS,
                 unavailable_counts: Tuple[Union[Counter, str], ...] = UNAVAILABLE_COUNTS) -> None:
        self._pool = pool
        # Voice refuses a hit that came back after the budget; Chat never did, and keeps that.
        self._refuse_late_hits = refuse_late_hits
        self._deadline_counts = deadline_counts
        self._unavailable_counts = unavailable_counts

    def find(self, ask: Callable[[], Dict[str, Any]], started: float,
             budget_ms: Optional[float]) -> Tuple[Optional[dict], Optional[Verdict]]:
        try:
            if budget_ms is None:
                hit = ask()
            else:
                hit = self._pool.submit(ask).result(timeout=budget_ms / MS_PER_SECOND)
        except concurrent.futures.TimeoutError:
            return None, Verdict("LookupDeadline", f"lookup passed the {budget_ms}ms voice budget; "
                                                   "a late hit is worse than a fast miss", self._deadline_counts)
        except Exception as exc:  # noqa: BLE001 — an unreachable cache means "ask the model"
            return None, Verdict("CacheUnavailable", f"cache unavailable ({type(exc).__name__}); asking the model",
                                 self._unavailable_counts)
        took_ms = (time.monotonic() - started) * MS_PER_SECOND
        if self._refuse_late_hits and budget_ms is not None and took_ms > budget_ms:
            return hit, Verdict("LookupDeadline", f"lookup took {took_ms:.1f}ms, past the {budget_ms}ms "
                                                  "voice budget; a late hit is worse than a fast miss",
                                self._deadline_counts)
        return hit, None
