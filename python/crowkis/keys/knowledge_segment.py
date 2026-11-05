"""KnowledgeSegment: the segment a channel's answers are looked up and saved in, per knowledge version."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Optional, Sequence, Tuple

if TYPE_CHECKING:  # the turns package imports these keys, so a runtime import would be a cycle
    from ..turns.values import Channel

# A value can never add or change a field of the segment.
_FIELD_BREAKERS = re.compile(r"[;=\s]+")


def follow_up_key(said: str, chain: Optional[Sequence[str]] = None) -> str:
    """A voice turn's key: its words as said, or the earlier turns it leans on joined to it."""
    return " || ".join([*chain, said]) if chain else said


def segment(fields: Sequence[Tuple[str, str]]) -> str:
    """``name=value;...``: a value can never add or change a field, and whitespace is collapsed."""
    return ";".join(" ".join(f"{name}={re.sub(r'[;=]', '_', value)}".split()) for name, value in fields)


class KnowledgeSegment:
    """``kb=<version>``: one pool per tenant. Answers made with one knowledge version only ever meet
    each other, so changing the knowledge behind the answers is a deliberate new version, never a
    silent mix. Voice and chat, with or without an understander, share it."""

    def __init__(self, version: str) -> None:
        self.version = _FIELD_BREAKERS.sub("_", str(version).strip()) or "1"

    @property
    def segment(self) -> str:
        return segment([("kb", self.version)])
