"""ChatReading: one chat turn as read (the understanding model's frame), then as checked."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from ..understanding.turn_frame import TurnFrame

if TYPE_CHECKING:
    from ..rules.rule_checker import Verdict as ChatVerdict


@dataclass(frozen=True)
class ChatReading:
    """The user's words (``text``, spaces normalised), the frame read from them, the names given in
    the turn, whether it tells something about the user (``about_caller``), and, once checked, the
    rule checker's ``verdict`` (route, reasons, and for a shared question its key and segment)."""

    text: str
    frame: Optional[TurnFrame] = None
    names: List[str] = field(default_factory=list)
    about_caller: bool = False
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
        """The shared question's segment (sent even when None, as Chat always did)."""
        return {"segment": self.verdict.segment}
