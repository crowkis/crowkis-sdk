"""SessionCall: a VoiceSession seen through the VoiceCall interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .channel import VOICE, Channel


class SessionCall:
    """Adapter: the VoiceCall a VoiceSession offers its rules. It only forwards to the
    session's own settings and checks, so the rules depend on the interface, not the session."""

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def channel(self) -> Channel:
        return VOICE

    @property
    def tainted(self) -> bool:
        return self._session._tainted

    @property
    def values(self) -> Dict[str, str]:
        return self._session.values

    @property
    def min_words(self) -> int:
        return self._session.min_words

    @property
    def short_turns(self) -> bool:
        return self._session.short_turns

    @property
    def serve_above(self) -> float:
        return self._session.serve_above

    @property
    def commitments(self) -> str:
        return self._session.commitments

    def is_personal(self, text: str) -> bool:
        return self._session._call_readings.is_personal(text)

    def mark_tainted(self) -> None:
        self._session._tainted = True

    def engine_vouches(self) -> bool:
        return self._session._engine_vouches()

    def chain(self) -> Optional[List[str]]:
        return self._session._chain()

    def after_urgent(self, text: str) -> bool:
        return self._session._after_urgent(text)

    def context_key(self, said: str, text: str) -> Optional[str]:
        return self._session._context_key(said, text)

    def answers_another_question(self, asked: str, answer: str, spent_ms: float) -> bool:
        return self._session._answers_another_question(asked, answer, spent_ms)

    def said_identifiers(self) -> Set[str]:
        return self._session._said_identifiers()

    def agent_key(self) -> Tuple:
        return self._session._agent_key()
