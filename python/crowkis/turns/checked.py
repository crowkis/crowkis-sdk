"""Checked and LookedUp: what one step of a turn found."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .verdict import Verdict


@dataclass(frozen=True)
class Checked:
    """A step's subject (the turn, the answer) as the next step reads it, and the objection that
    stops the turn there, if any."""

    subject: Any
    objection: Optional[Verdict] = None


@dataclass(frozen=True)
class LookedUp:
    """The cache's raw ``hit`` for a turn (None when there was none in time), the hit as the hit
    rules read it (``cached``, None when no hit was checked), and the objection that sends the turn
    to the model instead, if any."""

    hit: Optional[Dict[str, Any]]
    cached: Any = None
    objection: Optional[Verdict] = None
