"""A chat turn as read (ChatReading, ChatReader, ChatTurn) and the model's answer to it (ChatAnswer)."""

from __future__ import annotations

import concurrent.futures
import copy
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Optional, Set, TYPE_CHECKING, Tuple

from ...runtime.deadline import within
from ...state.call_state import CallState
from ...understanding.word_rules.chat import _names, _told
from ...understanding.model.frame import TurnFrame
from ...understanding.word_rules.call_context import _instructs, _tells_about_caller
from ...understanding.word_rules.personal import _identifiers
from ...understanding.word_rules.text import _words

if TYPE_CHECKING:
    from ...channels.call_session import CallSession
    from ...rules.rule_checker import Verdict as ChatVerdict

class ChatTurn:
    """A user's turn in a chat (``text``), the understanding model's frame of it, and the chat's
    state so far. ``question`` is the frame's stand-alone question (None when it gave none)."""

    def __init__(self, frame: TurnFrame, text: str, state: CallState) -> None:
        self.frame = frame
        self.text = text
        self.state = state

    @property
    def question(self):
        return self.frame.question


class ChatAnswer:
    """The answer (``text``: its words, spaces normalised), the shared question's verdict (its
    question and the attributes in its key), the frame of the turn, the chat's state, and the
    system prompt the model read with ``prompt_key`` naming whose prompts it is compared with."""

    def __init__(self, text: str, verdict: Any, frame: Optional[TurnFrame], state: CallState, *,
                 instructions: str, prompt_key: Tuple, private: bool = False) -> None:
        self.text = text
        # The app built this answer from a tool's result (ChatToolResult keeps it in the chat).
        self.private = private
        self.verdict = verdict
        self.frame = frame
        self.state = state
        self.instructions = instructions
        self.prompt_key = prompt_key


@dataclass(frozen=True)
class ChatReading:
    """The user's words (``text``, spaces normalised), the frame read from them, the names given in
    the turn, whether it tells something about the user (``about_caller``), the turn's number
    (``turn_id``), and, once checked, the rule checker's ``verdict`` (route, reasons, and for a shared
    question its key and segment)."""

    text: str
    frame: Optional[TurnFrame] = None
    names: List[str] = field(default_factory=list)
    about_caller: bool = False
    turn_id: int = 0
    verdict: Optional["ChatVerdict"] = None

    def checked_as(self, verdict: "ChatVerdict") -> "ChatReading":
        """This reading with the check's verdict."""
        return replace(self, verdict=verdict)

    @property
    def key(self) -> Optional[str]:
        """The shared question's key."""
        return self.verdict.key

    @property
    def lookup_options(self) -> Dict[str, Any]:
        """The shared question's segment, sent only when there is one (Agent.ask drops an empty one anyway)."""
        return {"segment": self.verdict.segment} if self.verdict.segment else {}


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
