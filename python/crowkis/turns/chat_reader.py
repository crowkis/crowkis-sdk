"""ChatReader: how a chat turn is understood, as TurnCore's TurnReader."""

from __future__ import annotations

import concurrent.futures
import copy
from typing import TYPE_CHECKING, Set

from ..runtime.deadline import within
from ..state.call_state import CallState
from ..understanding.turn_frame import TurnFrame
from ..understanding.chat_details import _names, _told
from ..understanding.word_rules import _identifiers, _instructs, _tells_about_caller, _words
from .chat_reading import ChatReading

if TYPE_CHECKING:
    from ..channels.call_session import CallSession

REPLAY_ONLY = "replay_only"


class ChatReader:
    """Reads a user's turn: its frame, then what the user tells (an allergy, an age, a trip), the
    names and IDs they give and a language they ask for, noted in the chat's state before any check,
    this turn's included.

    The frame is the one place a chat's understanding fails open: the model reads the turn within
    its budget (``runtime.deadline``, on ``pool``, with its own copy of the state); late or failing,
    the safe fallback (``replay``, exact repeats only) reads it, or the frame is an uncertain one.
    Each such turn is counted in the chat's counts (``understand_timeouts``, ``understand_errors``,
    ``fallback_used``); nothing is logged, as Chat never logged them. In replay-only mode the
    fallback alone reads every turn."""

    def __init__(self, session: CallSession, pool: concurrent.futures.Executor) -> None:
        self._session = session
        self._pool = pool

    def read(self, said: str, turn: int) -> ChatReading:
        state = self._session.state
        text = " ".join((said or "").split())
        words = _words(text)
        about_caller = _tells_about_caller(text)
        frame = self._frame(text)
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

    def _frame(self, text: str) -> TurnFrame:
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
