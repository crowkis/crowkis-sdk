"""WriteResult: what a bounded write did."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..turns.values import Verdict


@dataclass(frozen=True)
class WriteResult:
    """``written`` when the store finished in time. Otherwise either ``objection`` is the
    ``BoundedWrite`` verdict saying why not (``slow_write``: not written because too many writes wait
    on a slow server, or not confirmed within the deadline), or the store failed before the deadline
    (``refused``: the server refused the write, or the cache is down) with ``error``."""

    objection: Optional[Verdict] = None
    error: Optional[Exception] = None

    @property
    def written(self) -> bool:
        """Whether the store finished in time."""
        return self.objection is None and self.error is None

    @property
    def refused(self) -> bool:
        """Whether the store failed before the deadline."""
        return self.error is not None


WRITTEN = WriteResult()
