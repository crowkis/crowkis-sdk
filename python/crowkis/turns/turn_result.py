"""TurnResult: what a Chat session decided for one turn."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..understanding.turn_frame import TurnFrame
from .routes import SHARED

Message = Dict[str, str]


@dataclass
class TurnResult:
    turn_id: int
    route: str
    text: Optional[str] = None             # what to say now (cache hit or filler), else None
    needs_model: bool = True
    messages: Optional[List[Message]] = None  # what the model reads; None = the whole call
    frame: Optional[TurnFrame] = None
    verdict: Optional[Any] = None  # a Verdict; the real class would make an import cycle
    reason: str = ""

    @property
    def served_from_cache(self) -> bool:
        return self.route == SHARED and self.text is not None
