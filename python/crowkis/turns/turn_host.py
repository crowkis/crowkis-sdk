"""TurnHost: what TurnCore uses of the session that hosts it."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Union


class TurnHost(Protocol):
    """The call's own state and services, which stay in the session (VoiceSession). TurnCore reads
    and adds to these, and nothing else of the session; the stats() counters (``filled``, ``served``,
    ``inferred``, ...) are added to by name."""

    transcript: List[Dict[str, Any]]
    agent: Any
    serve_above: float
    latency_budget_ms: Optional[float]
    ttl: Optional[int]
    _fillers: Dict[str, str]
    _rule_counts: Any
    _last_stored: Optional[str]
    learn_errors: int
    filled: int
    served: int

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        """Audio for a spoken answer, when the session caches audio."""

    def _learn(self, *args: Any, **kwargs: Any) -> Any:
        """The bounded write of a shared answer: None when done, else the slow_write outcome."""

    def _learn_personal(self, keyed: str, model_said: str) -> Union[bool, Any]:
        """A shared shape from a personal answer: True when written, else False or slow_write."""

    def _keep_question(self, question: str, answer: str) -> None:
        """Note, in the background, the question an answer was saved for."""

    def _context_key(self, caller_said: str, text: str) -> Optional[str]:
        """The cache key of a turn: its words, or its chain for a follow-up."""
