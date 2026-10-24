"""ChatUnderstanding: a chat turn's frame from the app's understander, inside its one error boundary."""

from __future__ import annotations

import concurrent.futures
import copy
from typing import Any, Dict, Optional, Protocol

from ..runtime.deadline import within
from ..state.call_state import CallState
from ..understanding.turn_frame import TurnFrame

REPLAY_ONLY = "replay_only"


class ChatSessionUnderstanding(Protocol):
    """What ChatUnderstanding reads of the chat, live: an app may change these between turns."""

    state: CallState
    counts: Dict[str, int]
    mode: str
    understander: Any
    replay: Any
    understand_budget_ms: Optional[float]


class ChatUnderstanding:
    """The one place a chat's understanding fails open: the model reads the turn within its budget
    (``runtime.deadline``, on ``pool``, with its own copy of the state); late or failing, the safe
    fallback (``replay``, exact repeats only) reads it, or the frame is an uncertain one. Each such
    turn is counted in the chat's counts (``understand_timeouts``, ``understand_errors``,
    ``fallback_used``); nothing is logged, as Chat never logged them. In replay-only mode the
    fallback alone reads every turn."""

    def __init__(self, session: ChatSessionUnderstanding, pool: concurrent.futures.Executor) -> None:
        self._session = session
        self._pool = pool

    def frame(self, text: str) -> TurnFrame:
        """The turn's frame: the model's in time, otherwise the safe fallback's, or an uncertain one."""
        session = self._session
        if session.mode == REPLAY_ONLY:
            return self._replay_only(text)
        try:
            return self._model_frame(text)
        except concurrent.futures.TimeoutError:
            session.counts["understand_timeouts"] += 1
        except Exception:  # noqa: BLE001 - understanding failing must never end a call
            session.counts["understand_errors"] += 1
        return self._fallback(text)

    def _model_frame(self, text: str) -> TurnFrame:
        session = self._session
        if session.understand_budget_ms is None:
            return session.understander.understand(text, session.state)
        # The worker gets its own copy of the state: a late model must never see (or race
        # with) the state of a later turn. Its late answer is simply discarded.
        state = copy.deepcopy(session.state)
        return within(self._pool, session.understand_budget_ms, session.understander.understand, text, state)

    def _replay_only(self, text: str) -> TurnFrame:
        session = self._session
        if session.replay is None:
            return TurnFrame.from_dict(None)
        session.counts["fallback_used"] += 1
        return session.replay.understand(text, session.state)

    def _fallback(self, text: str) -> TurnFrame:
        session = self._session
        if session.replay is not None and session.replay is not session.understander:
            session.counts["fallback_used"] += 1
            try:
                return session.replay.understand(text, session.state)
            except Exception:  # noqa: BLE001 - the fallback failing too leaves an uncertain frame
                pass
        return TurnFrame.from_dict(None)
