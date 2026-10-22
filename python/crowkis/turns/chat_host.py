"""ChatHost: what ChatCore uses of the Chat session that hosts it."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol, Tuple

from ..callstate import CallState


class ChatHost(Protocol):
    """The chat's own state, counts, settings and hooks, which stay with the session (CallSession);
    public settings an app may change at any time are read here on every turn."""

    state: CallState
    counts: Dict[str, int]
    mode: str
    agent: Any
    understander: Any
    checker: Any
    replay: Any
    serve_above: float
    latency_budget_ms: Optional[float]
    understand_budget_ms: Optional[float]
    on_urgent: Optional[Callable[..., None]]
    urgent_reply: Optional[str]
    on_tools: Optional[Callable[..., Optional[str]]]
    instructions: str

    @property
    def fillers(self) -> Dict[str, str]:
        """Registered fillers, by normalised trigger."""

    def emit(self, event: Dict[str, Any]) -> None:
        """Send a monitoring event (never raises)."""

    def prompt_key(self) -> Tuple:
        """Whose system prompts this chat's is compared with."""
