"""ChatReader: how a chat turn is understood, as TurnCore's TurnReader."""

from __future__ import annotations

from typing import TYPE_CHECKING, Set

from ..state.call_state import CallState
from ..understanding.chat_details import _names, _told
from ..understanding.word_rules import _identifiers, _instructs, _tells_about_caller, _words
from .chat_reading import ChatReading
from .chat_understanding import ChatUnderstanding

if TYPE_CHECKING:
    from ..channels.call_session import CallSession


class ChatReader:
    """Reads a user's turn: its frame (``understanding``, which fails open), then what the user tells
    (an allergy, an age, a trip), the names and IDs they give and a language they ask for, noted in
    the chat's state before any check, this turn's included."""

    def __init__(self, session: CallSession, understanding: ChatUnderstanding) -> None:
        self._session = session
        self._understanding = understanding

    def read(self, said: str, turn: int) -> ChatReading:
        state = self._session.state
        text = " ".join((said or "").split())
        words = _words(text)
        about_caller = _tells_about_caller(text)
        frame = self._understanding.frame(text)
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
