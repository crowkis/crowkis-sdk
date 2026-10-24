"""A model answer waiting until Bolna has really spoken it."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional, Sequence

from ...voice import TurnDecision

ASSISTANT_ROLE = "assistant"

Recorder = Callable[[TurnDecision, str, Optional[str]], Awaitable[None]]


def squash(text: Any) -> str:
    """Text with its whitespace made single spaces, so spacing never decides a match."""
    return " ".join(text.split()) if isinstance(text, str) else ""


@dataclass
class PendingAnswer:
    """A finished model answer, held until Bolna's history shows it in full.

    Bolna writes a reply to its history only once the audio went out, and trims it when the
    caller talks over it. So the answer is saved only when the history row for its
    ``response_uid`` equals the text; anything else (no row, a trimmed row, another reply)
    is dropped. With no task manager to ask (``history`` is None) the answer is trusted and
    saved. Over-dropping only costs cache hits."""

    decision: TurnDecision
    text: str
    instructions: Optional[str]
    response_uid: Optional[str]

    def committed_in(self, history: Optional[Sequence[Any]]) -> bool:
        """Whether Bolna's history holds this answer, whole."""
        if history is None:
            return True
        if self.response_uid is None:
            return False
        for row in reversed(history):
            if row.get("role") == ASSISTANT_ROLE and row.get("response_uid") == self.response_uid:
                return squash(row.get("content")) == squash(self.text)
        return False

    async def settle(self, history: Optional[Sequence[Any]], record: Recorder) -> bool:
        """Save the answer when committed; True when it was handed to ``record``."""
        if not self.committed_in(history):
            return False
        await record(self.decision, self.text, self.instructions)
        return True
