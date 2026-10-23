"""ChatCachedAnswer: a Chat hit, as the hit rules read it."""

from __future__ import annotations

from typing import Optional

from ..runtime.question_records import QuestionRecords
from .hit import Hit

# Chat speaks a cached commitment (a price, a refund, a policy) only for the exact same question (decision V2).
CHAT_COMMITMENTS = "exact"


class ChatHitCall:
    """Adapter: the call a Chat hit belongs to, as the hit rules read it (the voice VoiceCall's hit side)."""

    commitments = CHAT_COMMITMENTS

    def __init__(self, records: QuestionRecords, budget_ms: Optional[float]) -> None:
        self._records = records
        self._budget_ms = budget_ms

    def answers_another_question(self, asked: str, answer: str, spent_ms: float) -> bool:
        """Every question the cached answer was saved for asks about something else (read within
        what the lookup left of the budget)."""
        left = None if self._budget_ms is None else self._budget_ms - spent_ms
        return self._records.answers_another_question(asked, answer, left)


class ChatHitTurn:
    """The shared question a Chat hit answers: never personal (only a shared question is looked up)."""

    is_personal = False

    def __init__(self, key: str, call: ChatHitCall) -> None:
        self.key = key
        self.call = call


class ChatCachedAnswer:
    """What the cache returned for a Chat question. ``started`` is when the lookup began
    (``time.monotonic()``)."""

    def __init__(self, turn: ChatHitTurn, hit: Hit, started: float) -> None:
        self.turn = turn
        self.hit = hit
        self.started = started

    @property
    def answer(self) -> str:
        return self.hit.answer
