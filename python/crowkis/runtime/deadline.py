"""within(): a hard deadline on work run on a pool (the twin of Node's ``runtime/deadline.js``)."""

from __future__ import annotations

import concurrent.futures
from typing import Any, Callable, TypeVar

MS_PER_SECOND = 1000.0
Result = TypeVar("Result")


def within(pool: concurrent.futures.Executor, budget_ms: float, work: Callable[..., Result], *args: Any) -> Result:
    """``work(*args)`` run on ``pool``, waited for no longer than ``budget_ms``: past it,
    ``concurrent.futures.TimeoutError`` is raised, work still queued is cancelled (it never runs, so a
    hung server cannot grow a queue of late lookups) and work already running keeps going, its result
    ignored. An error the work ends with in time is raised as it is."""
    future = pool.submit(work, *args)
    try:
        return future.result(timeout=budget_ms / MS_PER_SECOND)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise
