"""TurnDecision: what a voice session decided for one turn; _Outcome: what record() did with an answer."""

from __future__ import annotations

import weakref
from typing import Dict, List, Optional


class _Outcome(str):
    """An outcome word ("saved", "kept", ...) that also says, in ``why``, why an answer
    was not stored, and in ``rule`` which save rule decided it. Compares and serialises as
    the plain word."""

    why: str
    rule: Optional[str]

    def __new__(cls, word: str, why: str = "", rule: Optional[str] = None) -> "_Outcome":
        outcome = super().__new__(cls, word)
        outcome.why = why
        outcome.rule = rule
        return outcome


class TurnDecision:

    def __init__(
        self,
        action: str,
        *,
        text: Optional[str] = None,
        audio: Optional[bytes] = None,
        confidence: float = 0.0,
        reason: str = "",
        rule: Optional[str] = None,
    ) -> None:
        self.action = action
        self.text = text
        self.audio = audio
        self.confidence = confidence
        self.reason = reason
        # The rule behind the action (None for a confident hit), and after record() the
        # rule that kept the answer out of the cache (None when it was stored). Names are
        # the v4 rule names, so a decision can be traced to the one check that made it.
        self.rule = rule
        self.save_rule: Optional[str] = None
        # For a model turn: what the model must read, and whether its answer is shared.
        # None means "the whole call", and then the answer is never shared.
        self.messages: Optional[List[Dict[str, str]]] = None
        self.cacheable = False
        # Which turn of the call this is; an answer recorded for an older turn is dropped.
        self.turn = 0
        # After answer(): whether the model's answer was stored, and if not, why.
        self.stored = False
        self.not_stored = ""
        self._empty = False
        self._audio_shareable = False
        # Set by decide(): the session that made it (a weak reference, so a kept
        # decision never keeps a call alive) and, for a model turn, what the caller
        # said, so record() takes a decision only from its own session, and only once.
        # The caller's words are dropped once recorded.
        self._session: Optional["weakref.ReferenceType[VoiceSession]"] = None
        self._said: Optional[str] = None
        self._recorded = False

    @property
    def audio_shareable(self) -> bool:
        """Whether the spoken audio of this answer may go to the shared audio cache:
        not for an answer filled with this caller's values."""
        return self._audio_shareable

    @property
    def served_from_cache(self) -> bool:
        return self.action == "serve"

    @property
    def served_from_filler(self) -> bool:
        return self.action == "filler"

    @property
    def needs_model(self) -> bool:
        return self.action == "infer"

    @property
    def empty(self) -> bool:
        """After answer(): the model was asked and said nothing (the action stays
        "infer"); retry, or speak a fallback."""
        return self._empty

    def __repr__(self) -> str:
        return (
            f"TurnDecision({self.action!r}, confidence={self.confidence:.4f}, "
            f"reason={self.reason!r})"
        )
