"""NoRewrite: the rewriter slot left empty."""

from __future__ import annotations

from typing import Any, Optional


class NoRewrite:
    """Null Object for the rewriter slot: no stand-alone question, so a turn's cache key stays
    the caller's own words (or the chain a follow-up leans on), as today."""

    def rewrite(self, text: str, reading: Any) -> Optional[str]:
        return None
