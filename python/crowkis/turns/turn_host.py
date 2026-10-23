"""TurnHost: what the voice parts of TurnCore use of the session that hosts them."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Union


class TurnHost(Protocol):
    """The call's own state and services, which stay with the session: its transcript, the agent
    lookups go through, its settings, the audio for a spoken answer and the writes of an answer.
    The voice parts (VoiceReport, VoiceSaving, VoicePairing) and TurnCore (as its CallSettings) use
    these and nothing else of the session (the session's counters are ``Stats``)."""

    @property
    def transcript(self) -> List[Dict[str, Any]]:
        """The call's turns so far; the core adds a served turn to it."""

    @property
    def agent(self) -> Any:
        """The agent lookups go through."""

    @property
    def serve_above(self) -> float:
        """The confidence a cached answer needs to be spoken."""

    @property
    def latency_budget_ms(self) -> Optional[float]:
        """The call's budget for a lookup, read when it looks up."""

    @property
    def ttl(self) -> Optional[int]:
        """How long a saved answer lives."""

    def voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        """Audio for a spoken answer, when the session caches audio."""

    def learn(self, key: str, answer: str, *, ttl: Optional[int]) -> Any:
        """The bounded write of a shared answer: None when done, else the slow_write outcome."""

    def learn_personal(self, key: str, answer: str) -> Union[bool, Any]:
        """A shared shape from a personal answer: True when written, else False or slow_write."""

    def keep_question(self, question: str, answer: str) -> None:
        """Note, in the background, the question an answer was saved for."""

    def context_key(self, said: str, text: str) -> Optional[str]:
        """The cache key of a turn: its words, or its chain for a follow-up."""

    def note_stored(self, key: str) -> None:
        """The question the latest shared answer was stored under."""
