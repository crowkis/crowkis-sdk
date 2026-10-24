"""WriteResult: what a bounded write did."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..turns.verdict import Verdict


@dataclass(frozen=True)
class WriteResult:
    """``written`` when the store finished in time; otherwise ``objection`` is the ``BoundedWrite``
    verdict saying why not (``slow_write``: not written because too many writes wait on a slow server,
    or not confirmed within the deadline)."""

    objection: Optional[Verdict] = None

    @property
    def written(self) -> bool:
        """Whether the store finished in time."""
        return self.objection is None


WRITTEN = WriteResult()
