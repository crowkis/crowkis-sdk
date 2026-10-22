"""FakeCall: a VoiceCall for testing one rule alone."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple

from crowkis.turns.channel import VOICE, Channel


@dataclass
class FakeCall:
    """A call with fixed settings; every check answers what the test set."""

    tainted: bool = False
    values: Dict[str, str] = field(default_factory=dict)
    min_words: int = 3
    short_turns: bool = False
    serve_above: float = 0.92
    commitments: str = "exact"
    vouches: bool = False
    earlier: Optional[List[str]] = field(default_factory=list)
    urgent_before: bool = False
    key: Optional[str] = "the key"
    another_question: bool = False
    identifiers: Set[str] = field(default_factory=set)
    channel: Channel = VOICE

    def mark_tainted(self) -> None:
        self.tainted = True

    def engine_vouches(self) -> bool:
        return self.vouches

    def chain(self) -> Optional[List[str]]:
        return self.earlier

    def after_urgent(self, text: str) -> bool:
        return self.urgent_before

    def context_key(self, said: str, text: str) -> Optional[str]:
        return self.key

    def answers_another_question(self, asked: str, answer: str, spent_ms: float) -> bool:
        return self.another_question

    def said_identifiers(self) -> Set[str]:
        return self.identifiers

    def agent_key(self) -> Tuple:
        return (None, None)
