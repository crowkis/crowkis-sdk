"""VoiceCall: what a rule may read about the call a turn belongs to."""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Protocol, Set, Tuple

if TYPE_CHECKING:
    from .channel import Channel


class VoiceCall(Protocol):
    """The call as the rules see it: its settings and what it has heard so far. Rules read it
    and never reach into the session; the one change they make is ``mark_tainted``."""

    @property
    def channel(self) -> "Channel":
        """What the call's channel can do (spoken, audio, ...)."""

    @property
    def tainted(self) -> bool:
        """The caller has told this call something a later answer may depend on."""

    @property
    def values(self) -> Dict[str, str]:
        """The caller's values declared for this call (to fill a shared answer shape)."""

    @property
    def min_words(self) -> int:
        """A turn with fewer words is too short to match on meaning."""

    @property
    def short_turns(self) -> bool:
        """Whether a short turn may be served an exact, vouched answer."""

    @property
    def serve_above(self) -> float:
        """The confidence a cached answer needs to be spoken."""

    @property
    def commitments(self) -> str:
        """How a cached commitment (a price, a refund, a policy) may be spoken."""

    def mark_tainted(self) -> None:
        """Remember that the caller has told this call something."""

    def engine_vouches(self) -> bool:
        """Whether the server's decision engine judges what it caches."""

    def chain(self) -> Optional[List[str]]:
        """The earlier turns a follow-up leans on, or None when it cannot be resolved."""

    def after_urgent(self, text: str) -> bool:
        """The turn follows an urgent turn of this call."""

    def context_key(self, said: str, text: str) -> Optional[str]:
        """The cache key of a turn: its words, or its chain for a follow-up; None without one."""

    def answers_another_question(self, asked: str, answer: str, spent_ms: float) -> bool:
        """Every question the cached answer was saved for asks about something else."""

    def said_identifiers(self) -> Set[str]:
        """The ID-like values this caller said earlier in the call."""

    def agent_key(self) -> Tuple:
        """Which agent's system prompts this call's is compared with."""
