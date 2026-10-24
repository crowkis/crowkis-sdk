"""AppHooks: the app's chat hooks, inside their one error boundary."""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol

from ..understanding.turn_frame import TurnFrame


class ChatSessionAppHooks(Protocol):
    """The hooks the app set on the chat, read live: an app may change them between turns."""

    on_urgent: Optional[Callable[[str, TurnFrame], None]]
    on_tools: Optional[Callable[[str, TurnFrame], Optional[str]]]
    on_event: Optional[Callable[[Dict[str, Any]], None]]


class AppHooks:
    """The one place a failing app hook is caught: an urgent-turn hook or a monitoring hook that
    fails changes nothing, and a failing tool means the model answers. Never ends the chat. The
    callers call a hook only when the app set one."""

    def __init__(self, session: ChatSessionAppHooks) -> None:
        self._session = session

    def urgent(self, text: str, frame: TurnFrame) -> None:
        """The app's ``on_urgent`` hook, told of an urgent turn."""
        try:
            self._session.on_urgent(text, frame)
        except Exception:  # noqa: BLE001 - the hook must not take the call down
            pass

    def tools(self, text: str, frame: TurnFrame) -> Optional[str]:
        """The app's ``on_tools`` answer to a personal or live turn; None when it fails."""
        try:
            return self._session.on_tools(text, frame)
        except Exception:  # noqa: BLE001 - a failing tool means the model answers
            return None

    def event(self, event: Dict[str, Any]) -> None:
        """The app's ``on_event`` monitoring hook, sent one event."""
        try:
            self._session.on_event(event)
        except Exception:  # noqa: BLE001 - monitoring must never affect the call
            pass
