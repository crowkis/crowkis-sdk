"""Hit: what the cache returned for a turn's key, typed once at the lookup."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

CACHE_ROUTE = "cache"


@dataclass(frozen=True)
class Hit:
    """The agent's answer to a lookup: its route ("cache" when confident enough to speak), the answer
    text, the confidence, and the flags the server's decision engine set (an exact match, vouched for,
    a commitment such as a price or a policy)."""

    route: str
    answer: Optional[str]
    confidence: float
    exact: bool = False
    vouched: bool = False
    commitment: bool = False
    unjudged: bool = False  # a reworded match the server's engine has not judged yet

    @classmethod
    def from_agent(cls, hit: Dict[str, Any]) -> "Hit":
        """Built once from Agent.ask's result."""
        return cls(route=hit["route"], answer=hit.get("answer"), confidence=hit.get("confidence", 0.0),
                   exact=bool(hit.get("exact")), vouched=bool(hit.get("vouched")),
                   commitment=bool(hit.get("commitment")), unjudged=bool(hit.get("unjudged")))

    @property
    def is_confident(self) -> bool:
        return self.route == CACHE_ROUTE
