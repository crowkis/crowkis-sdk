"""ChatReader: how a chat turn is understood, as TurnCore's TurnReader."""

from __future__ import annotations

import concurrent.futures
import copy
from typing import Any, Dict, Optional, Protocol, Set

from ..state.call_state import CallState
from ..understanding.chat_details import _names, _told
from ..understanding.turn_frame import TurnFrame
from ..understanding.word_rules import _identifiers, _instructs, _tells_about_caller, _words
from .chat_reading import ChatReading

REPLAY_ONLY = "replay_only"
MS_PER_SECOND = 1000.0


class ChatSessionUnderstanding(Protocol):
    """What ChatReader reads of the chat, live: an app may change these between turns."""

    state: CallState
    counts: Dict[str, int]
    mode: str
    understander: Any
    replay: Any
    understand_budget_ms: Optional[float]


class ChatReader:
    """Reads a user's turn with the understanding model, within its budget (``pool`` runs it); late
    or failing, the safe fallback (``replay``, exact repeats only) reads it, or the frame is an
    uncertain one. What the user tells (an allergy, an age, a trip), the names and IDs they give and
    a language they ask for are noted in the chat's state before any check, this turn's included."""

    def __init__(self, session: ChatSessionUnderstanding, pool: concurrent.futures.Executor) -> None:
        self._session = session
        self._pool = pool

    def read(self, said: str, turn: int) -> ChatReading:
        state = self._session.state
        text = " ".join((said or "").split())
        words = _words(text)
        about_caller = _tells_about_caller(text)
        frame = self._understand(text)
        named: Set[str] = set()
        if about_caller:
            named, details = _told(text, frame)
            state.note_stated(" ".join(w for w in words if w not in named))
            state.note_details(details)
        # On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah.
        # What is the refund policy?") is never in a shared question or answer.
        names = sorted(set(_names(text, frame, fact=about_caller)) | named)
        state.note_names(names)
        state.note_identifiers(_identifiers([text]))
        if frame.language and _instructs(text, words):
            state.language = frame.language  # "reply only in Hindi": kept for the rest of the chat
        return ChatReading(text, frame, names, about_caller, turn)

    def _understand(self, text: str) -> TurnFrame:
        """The model's frame within the budget; otherwise the safe fallback's, or an uncertain one."""
        session = self._session
        if session.mode == REPLAY_ONLY:
            if session.replay is None:
                return TurnFrame.from_dict(None)
            session.counts["fallback_used"] += 1
            return session.replay.understand(text, session.state)
        try:
            if session.understand_budget_ms is None:
                return session.understander.understand(text, session.state)
            # The worker gets its own copy of the state: a late model must never see (or race
            # with) the state of a later turn. Its late answer is simply discarded.
            state = copy.deepcopy(session.state)
            return self._pool.submit(session.understander.understand, text, state).result(
                timeout=session.understand_budget_ms / MS_PER_SECOND)
        except concurrent.futures.TimeoutError:
            session.counts["understand_timeouts"] += 1
        except Exception:  # noqa: BLE001 - understanding failing must never end a call
            session.counts["understand_errors"] += 1
        if session.replay is not None and session.replay is not session.understander:
            session.counts["fallback_used"] += 1
            try:
                return session.replay.understand(text, session.state)
            except Exception:  # noqa: BLE001
                pass
        return TurnFrame.from_dict(None)
