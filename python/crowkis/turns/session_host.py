"""SessionHost: a VoiceSession seen through the TurnHost interface."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Union


class SessionHost:
    """Adapter: the TurnHost a VoiceSession offers its TurnCore. It only forwards to the session's
    own state and services, so the core depends on the interface, not the session's private parts."""

    def __init__(self, session: Any) -> None:
        self._session = session

    @property
    def transcript(self) -> List[Dict[str, Any]]:
        return self._session.transcript

    @property
    def agent(self) -> Any:
        return self._session.agent

    @property
    def serve_above(self) -> float:
        return self._session.serve_above

    @property
    def latency_budget_ms(self) -> Optional[float]:
        return self._session.latency_budget_ms

    @property
    def ttl(self) -> Optional[int]:
        return self._session.ttl

    def voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        return self._session._voiced(answer, cacheable=cacheable)

    @property
    def segment(self) -> Optional[str]:
        return self._session._segment

    def learn(self, key: str, answer: str, *, ttl: Optional[int]) -> Any:
        return self._session._learn(key, answer, ttl=ttl)

    def learn_personal(self, key: str, answer: str) -> Union[bool, Any]:
        return self._session._learn_personal(key, answer)

    def keep_question(self, question: str, answer: str) -> None:
        self._session._keep_question(question, answer)

    def context_key(self, said: str, text: str) -> Optional[str]:
        return self._session._context_key(said, text)

    def note_stored(self, key: str) -> None:
        self._session._last_stored = key
