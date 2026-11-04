"""ChatAnswers: what a chat answers without the cache or the model, as TurnCore's EarlyAnswers."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Dict, Optional

from ..state.call_state import CallState
from ..understanding.chat_details import _masked, _norm
from ..understanding.turn_frame import TurnFrame
from .app_hooks import AppHooks
from .chat_turns import ChatTurns
from .checked import Checked
from .routes import AGENT, FILLER, PERSONAL, TOOLS, URGENT
from .turn_result import TurnResult

if TYPE_CHECKING:
    from ..channels.call_session import CallSession

SHARING_OFF = "off"
URGENT_SCRIPT_REASON = "urgent script"
TOOLS_REASON = "answered by the business's tools"


class ChatAnswers:
    """Before a turn is read: an empty turn goes to the agent, a registered filler answers it, and
    with sharing off the agent answers everything. After the check: the app's ``on_urgent`` hook
    runs on an urgent turn and its ``urgent_reply`` answers it; ``on_tools`` may answer a personal
    or live turn. None of these is ever cached; a hook that fails never ends the chat (``hooks``)."""

    def __init__(self, session: CallSession, turns: ChatTurns, hooks: AppHooks) -> None:
        self._session = session
        self._turns = turns
        self._hooks = hooks

    def before_reading(self, said: str, turn_id: int) -> Optional[TurnResult]:
        session = self._session
        text = " ".join((said or "").split())
        if not text:
            return self._turns.await_answer(TurnResult(turn_id, AGENT, reason="empty"))
        filler = session.fillers.get(_norm(text))
        if filler is not None:
            session.counts[FILLER] += 1
            session.state.note_agent_reply(filler)
            return TurnResult(turn_id, FILLER, text=filler, needs_model=False, reason="registered filler")
        if session.mode == SHARING_OFF:
            session.counts["sharing_off"] += 1
            result = self._turns.await_answer(TurnResult(turn_id, AGENT, reason="sharing off"))
            session.emit({"type": "turn", "turn_id": turn_id, "route": AGENT, "reasons": ["mode_off"],
                          "shared": False})
            return result
        return None

    def after_check(self, checked: Checked) -> Optional[TurnResult]:
        reading = checked.subject
        route = reading.verdict.route
        if route == URGENT:
            return self._urgent(reading)
        if route in (TOOLS, PERSONAL):
            return self._tools(reading)
        return None

    def _urgent(self, reading: Any) -> Optional[TurnResult]:
        session = self._session
        if session.on_urgent is not None:
            self._hooks.urgent(reading.text, reading.frame)
        if not session.urgent_reply:
            return None
        session.state.note_agent_reply(session.urgent_reply)
        return TurnResult(reading.turn_id, URGENT, text=session.urgent_reply, needs_model=False,
                          frame=reading.frame, verdict=reading.verdict, reason=URGENT_SCRIPT_REASON)

    def _tools(self, reading: Any) -> Optional[TurnResult]:
        session = self._session
        if session.on_tools is None:
            return None
        answered = self._hooks.tools(reading.text, reading.frame)
        if not answered:
            return None
        session.counts["tools_answered"] += 1
        session.state.note_agent_reply(_masked(answered))
        return TurnResult(reading.turn_id, reading.verdict.route, text=answered, needs_model=False,
                          frame=reading.frame, verdict=reading.verdict, reason=TOOLS_REASON)
