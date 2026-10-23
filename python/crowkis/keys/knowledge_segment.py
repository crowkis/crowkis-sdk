"""KnowledgeSegment: the segment a channel's answers are looked up and saved in, per knowledge version."""

from __future__ import annotations

import re

from ..turns.channel import Channel

# A value can never add or change a field of the segment.
_FIELD_BREAKERS = re.compile(r"[;=\s]+")


class KnowledgeSegment:
    """``kb=<version>;channel=<name>``: answers made with one understanding (its prompt, its model) and
    knowledge version only ever meet each other, so switching understanders, or the knowledge behind
    the answers, is a deliberate new version, never a silent mix. Chat builds the same fields in its
    own, longer segment (RuleChecker.build_segment)."""

    def __init__(self, version: str, channel: Channel) -> None:
        self.version = _FIELD_BREAKERS.sub("_", str(version).strip()) or "1"
        self.channel = channel

    @property
    def segment(self) -> str:
        return f"kb={self.version};channel={self.channel.name}"
