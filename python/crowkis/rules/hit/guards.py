"""Hit rules: when a confident hit still goes to the model instead of being spoken.

A family of small rules, in the order a hit is checked."""

from __future__ import annotations

import time
from typing import Optional

from ...turns import CachedAnswer, Verdict
from ...understanding.word_rules import _COMMITMENTS, _PII_PLACEHOLDER, _speakable

MS_PER_SECOND = 1000.0
CACHE_ROUTE = "cache"
SLOT_MISSING_REASON = (
    "the shared answer shape has a slot this call has no value "
    "for; speaking a half-filled answer is worse than a model call"
)
PLACEHOLDER_REASON = (
    "the cached answer holds a placeholder the server put in place of a "
    "caller's detail; reading it aloud is worse than a model call"
)
DIFFERENT_QUESTION_REASON = (
    "the cached answer was saved for a different question (it asks about "
    "something this one does not); a model call is better than a wrong answer"
)
SHORT_TURN_REASON = (
    "a short turn is only answered from cache once the answer has been "
    "judged to stand on its own, and this one has not"
)
SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)"


class ConfidenceBar:
    """A hit below the spoken-answer bar (or a miss) goes to the model."""

    name = "ConfidenceBar"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if cached.hit["route"] == CACHE_ROUTE:
            return None
        reason = f"confidence below the spoken-answer bar of {cached.turn.call.serve_above}"
        return Verdict(self.name, reason, ("inferred",))


class TemplateSlotMissing:
    """A shared answer shape with a slot this call has no value for is never half spoken."""

    name = "TemplateSlotMissing"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_personal or cached.answer is not None:
            return None
        return Verdict(self.name, SLOT_MISSING_REASON, ("refused_private", "inferred"))


class PiiPlaceholder:
    """An answer holding a placeholder the server put in place of a caller's detail is never read aloud."""

    name = "PiiPlaceholder"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not _PII_PLACEHOLDER.search(cached.answer):
            return None
        return Verdict(self.name, PLACEHOLDER_REASON, ("refused_private", "inferred"))


class DifferentQuestion:
    """A near hit saved for a question that asks about something else is not served."""

    name = "DifferentQuestion"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        turn = cached.turn
        if turn.is_personal or cached.hit.get("exact"):
            return None
        spent_ms = (time.monotonic() - cached.started) * MS_PER_SECOND
        if not turn.call.answers_another_question(turn.key, cached.answer, spent_ms):
            return None
        return Verdict(self.name, DIFFERENT_QUESTION_REASON, ("different_question", "inferred"))


class ShortTurnUnvouched:
    """A short turn is served only an exact match the server's decision engine has vouched for."""

    name = "ShortTurnUnvouched"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_short or (cached.hit.get("vouched") and cached.hit.get("exact")):
            return None
        return Verdict(self.name, SHORT_TURN_REASON, ("inferred",))


class CommitmentRewording:
    """A commitment (a price, a refund, a policy) is spoken only as the call's ``commitments``
    setting allows: by default, only for the exact same question."""

    name = "CommitmentRewording"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        commitments = cached.turn.call.commitments
        if not cached.hit.get("commitment") or _COMMITMENTS[commitments](cached.hit):
            return None
        reason = ("the cached answer is a commitment (a price, a refund, a policy) and "
                  f"commitments={commitments!r} does not allow speaking this match")
        return Verdict(self.name, reason, ("held_commitments", "inferred"))


class ScreenOnlyAnswer:
    """An answer written for a screen (a link, code or markup) is not spoken."""

    name = "ScreenOnlyAnswer"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if _speakable(cached.answer):
            return None
        return Verdict(self.name, SCREEN_REASON, ("unspeakable", "inferred"))
