"""VoiceAnswered and ChatAnswered: the model's answer to a turn, as each facade hands it to record()."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Optional, Tuple

from .turn_result import TurnResult


@dataclass(frozen=True)
class VoiceAnswered:
    """A voice turn's answer: what the caller said, what the model said, the turn it answers (None:
    the latest), whether it was built from a tool's result (``private``), the system prompt the model
    read, and, once paired, whether decide() let it be shared (``shareable``)."""

    said: str
    model_said: str
    turn: Optional[int]
    private: bool
    instructions: Optional[str]
    shareable: bool = False

    def paired(self, shareable: bool) -> "VoiceAnswered":
        """This answer, paired with its turn: ``shareable`` is what decide() said for that turn."""
        return replace(self, shareable=shareable)


@dataclass(frozen=True)
class ChatAnswered:
    """A chat turn's answer: the turn's result, the agent's answer, the places / products / options it
    named (``mentions``), the task it started collecting details for, and whether the app built it
    from a tool's result (``private``)."""

    result: TurnResult
    answer: str
    mentions: Tuple = ()
    task: Optional[str] = None
    private: bool = False
