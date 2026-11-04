"""Stage 2 rules (hit): may a cached answer be spoken for this turn."""

from __future__ import annotations

import time
from typing import Callable, Dict, Optional

from ...runtime.stats import Counter
from ...turns.values import CachedAnswer, Verdict
from ...turns.values import Hit
from ...understanding.word_rules.answers import _speakable
from ...understanding.word_rules.text import _PII_PLACEHOLDER


# Commitment policies: how a cached commitment (a price, a refund, a policy) may be spoken.
# Strategy per VoiceSession(commitments=...) setting: serve any match, only the same question, or never.
COMMITMENT_POLICIES: Dict[str, Callable[[Hit], bool]] = {
    "serve": lambda hit: True,
    "exact": lambda hit: hit.exact,
    "never": lambda hit: False,
}


class CommitmentRewording:
    """A commitment (a price, a refund, a policy) is spoken only as the call's ``commitments``
    setting allows: by default, only for the exact same question."""

    name = "CommitmentRewording"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        commitments = cached.turn.call.commitments
        hit = cached.hit
        if not (hit.commitment or hit.unjudged) or COMMITMENT_POLICIES[commitments](hit):
            return None
        reason = ("the cached answer is a commitment (a price, a refund, a policy)" if hit.commitment
                  else "the cached answer has not been judged yet, so it may be a commitment") + (
                  f" and commitments={commitments!r} does not allow speaking this match")
        return Verdict(self.name, reason, (Counter.HELD_COMMITMENTS, Counter.INFERRED))


class ConfidenceBar:
    """A hit below the spoken-answer bar (or a miss) goes to the model."""

    name = "ConfidenceBar"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if cached.hit.is_confident:
            return None
        reason = f"confidence below the spoken-answer bar of {cached.turn.call.serve_above}"
        return Verdict(self.name, reason, (Counter.INFERRED,))


MS_PER_SECOND = 1000.0
DIFFERENT_QUESTION_REASON = (
    "the cached answer was saved for a different question (it asks about "
    "something this one does not); a model call is better than a wrong answer"
)


class DifferentQuestion:
    """A near hit saved for a question that asks about something else is not served."""

    name = "DifferentQuestion"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        turn = cached.turn
        if turn.is_personal or cached.hit.exact:
            return None
        spent_ms = (time.monotonic() - cached.started) * MS_PER_SECOND
        if not turn.call.answers_another_question(turn.key, cached.answer, spent_ms):
            return None
        return Verdict(self.name, DIFFERENT_QUESTION_REASON, (Counter.DIFFERENT_QUESTION, Counter.INFERRED))


PLACEHOLDER_REASON = (
    "the cached answer holds a placeholder the server put in place of a "
    "caller's detail; reading it aloud is worse than a model call"
)


class PiiPlaceholder:
    """An answer holding a placeholder the server put in place of a caller's detail is never read aloud."""

    name = "PiiPlaceholder"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not _PII_PLACEHOLDER.search(cached.answer):
            return None
        return Verdict(self.name, PLACEHOLDER_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


SCREEN_REASON = "the cached answer was written for a screen (a link, code or markup)"


class ScreenOnlyAnswer:
    """On a spoken channel, an answer written for a screen (a link, code or markup) is not spoken."""

    name = "ScreenOnlyAnswer"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.call.channel.spoken or _speakable(cached.answer):
            return None
        return Verdict(self.name, SCREEN_REASON, (Counter.UNSPEAKABLE, Counter.INFERRED))


SHORT_TURN_REASON = (
    "a short turn is only answered from cache once the answer has been "
    "judged to stand on its own, and this one has not"
)


class ShortTurnUnvouched:
    """A short turn is served only an exact match the server's decision engine has vouched for."""

    name = "ShortTurnUnvouched"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_short or (cached.hit.vouched and cached.hit.exact):
            return None
        return Verdict(self.name, SHORT_TURN_REASON, (Counter.INFERRED,))


SLOT_MISSING_REASON = (
    "the shared answer shape has a slot this call has no value "
    "for; speaking a half-filled answer is worse than a model call"
)


class TemplateSlotMissing:
    """A shared answer shape with a slot this call has no value for is never half spoken."""

    name = "TemplateSlotMissing"
    floor = False

    def check(self, cached: CachedAnswer) -> Optional[Verdict]:
        if not cached.turn.is_personal or cached.answer is not None:
            return None
        return Verdict(self.name, SLOT_MISSING_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
