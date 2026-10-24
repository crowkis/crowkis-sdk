"""BoundedWriter: a cache write a live turn waits for no longer than its deadline."""

from __future__ import annotations

import concurrent.futures
import logging
from typing import Any, Callable, Optional

from ..turns.verdict import Verdict
from .write_workers import WriteWorkers
from .stats import Counter

SLOW_WRITE = "slow_write"
NOT_WRITTEN_REASON = "not written: too many writes are waiting on a slow server"
NOT_CONFIRMED_REASON = ("not confirmed: the server took longer than the latency budget, so the write finishes "
                        "in the background")
# A turn waits for its answer's write at most this many latency budgets.
BUDGETS_PER_WRITE = 2
MS_PER_SECOND = 1000


class BoundedWriter:
    """Writes an answer and waits at most ``deadline_s``: a slow server never stalls the turn after
    a miss. A write still running then finishes on the workers (an error it ends with is counted).
    Past ``max_pending()`` writes already waiting on a slow server, a new answer is not written.

    ``max_pending`` is read when a write starts; ``count`` adds to a session counter; both are the
    session's, injected."""

    def __init__(self, workers: WriteWorkers, max_pending: Callable[[], int], count: Callable[[str], None],
                 log: logging.Logger) -> None:
        self._workers = workers
        self._max_pending = max_pending
        self._count = count
        self._log = log

    def write_within(self, store: Callable[..., Any], *args: Any, budget_ms: Optional[float],
                     **kwargs: Any) -> Optional[Verdict]:
        """``write`` waited for no longer than twice the turn's latency budget; without a budget
        (None) the store is waited for, as it always was. Voice and chat both write this way."""
        if budget_ms is None:
            store(*args, **kwargs)
            return None
        return self.write(store, *args, deadline_s=BUDGETS_PER_WRITE * budget_ms / MS_PER_SECOND, **kwargs)

    def write(self, store: Callable[..., Any], *args: Any, deadline_s: float, **kwargs: Any) -> Optional[Verdict]:
        """None when the write is done; otherwise the BoundedWrite verdict (not written, or not
        confirmed in time). An error before the deadline is raised, as before."""
        with self._workers.pending_lock:
            full = len(self._workers.pending) >= self._max_pending()
            if not full:
                future = self._workers.submit(store, *args, **kwargs)
                self._workers.pending.add(future)
        if full:
            self._count(Counter.SLOW_WRITES)
            self._log.warning("crowkis voice: too many writes waiting on a slow server; this answer is not written")
            return Verdict("BoundedWrite", NOT_WRITTEN_REASON, (), SLOW_WRITE)
        self._workers.hand_over(future)
        try:
            future.result(timeout=deadline_s)
        except concurrent.futures.TimeoutError:
            self._count(Counter.SLOW_WRITES)
            future.add_done_callback(self._late)
            return Verdict("BoundedWrite", NOT_CONFIRMED_REASON, (), SLOW_WRITE)
        return None

    def _late(self, future: concurrent.futures.Future) -> None:
        if future.exception() is not None:
            self._count(Counter.LEARN_ERRORS)
            self._log.warning("crowkis voice: a write that passed the latency budget then failed (%s)",
                              type(future.exception()).__name__)
