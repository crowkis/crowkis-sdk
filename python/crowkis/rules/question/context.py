"""Stage 1 rules (question): what the call said before (a private chain, a follow-up, a reference, stated facts)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns.values import Verdict
from ...turns.voice.turn import VoiceTurn
from ...understanding.word_rules.private_words import _unnamed
from ...understanding.model.checks import _content_stems, stated_fact_irrelevant
from ...understanding.word_rules.call_context import _sets_context
from ...understanding.word_rules.follow_up import _private_chain


PRIVATE_CHAIN_REASON = (
    "a follow-up to a private turn of this call: its answer depends on "
    "what this caller said, so it is never answered from a shared cache"
)


class PrivateChain:
    """A follow-up to a private turn of the call, or any turn after an urgent one, is private:
    its answer depends on what this caller said."""

    name = "PrivateChain"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        chain = turn.call.chain() or []
        follows_private = turn.is_context_dependent and (
            _private_chain(chain, turn.call.min_words) or any(turn.call.is_personal(earlier) for earlier in chain))
        if not (follows_private or turn.call.after_urgent(turn.text)):
            return None
        return Verdict(self.name, PRIVATE_CHAIN_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


NO_KEY_REASON = (
    "the utterance only has meaning against an earlier turn and this "
    "call has none, so no cache key can be built for it"
)


class FollowUpWithoutContext:
    """A follow-up ("and what about that") with no earlier turn to lean on has no cache key."""

    name = "FollowUpWithoutContext"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if turn.key is not None:
            return None
        return Verdict(self.name, NO_KEY_REASON, (Counter.INFERRED,))


TAINTED_REASON = (
    "the caller has told this call something a later answer may depend on "
    "(a condition, an age, a plan, an instruction, a step in their own task); "
    "a shared answer to the bare question could be wrong for them"
)


class CallContextTaint:
    """Once the caller tells the call something a later answer may depend on (a condition, an
    age, a plan, an instruction), every later turn of the call is private. The voice default
    until an understander can tell which stated facts change an answer."""

    name = "CallContextTaint"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if not (turn.call.tainted or _sets_context(turn.text)):
            return None
        turn.call.mark_tainted()
        return Verdict(self.name, TAINTED_REASON, (Counter.REFUSED_PRIVATE, Counter.INFERRED))


# The StatedFacts rule for voice with an understander (stage 1, question).
TELLS_REASON = "the turn tells the call something a later answer may depend on; its own answer stays with this caller"
DEPENDS_REASON = (
    "the caller told this call something that may change this answer (or the model could not say it does "
    "not); a shared answer to the bare question could be wrong for them"
)


def _hidden(stated: str, private) -> bool:
    """The model was sent this stated turn with a number or a content word masked ("flying to _ with _
    bags"), so it judged the turn without it: the turn counts."""
    return any(c.isdecimal() for c in stated) or bool(_content_stems(stated) - _content_stems(_unnamed(stated, private)))


class VoiceStatedFacts:
    """Replaces CallContextTaint when an understander is plugged in: a turn that tells the call
    something (a condition, an age, a plan) stays private, and so does each later turn unless the
    model is sure that none of the stated facts changes its answer and none is an allergy, a
    medication, a pregnancy or an age. Unsure, late or failed: private, as before. Instead of
    tainting the call, it keeps just that turn private (``mark_private``)."""

    name = "VoiceStatedFacts"
    floor = False

    def check(self, turn: VoiceTurn) -> Optional[Verdict]:
        if _sets_context(turn.text):
            return self._private(turn, TELLS_REASON)
        if turn.call.tainted:  # the call heard something its model never read (loaded history, a private turn)
            return self._private(turn, DEPENDS_REASON)
        private = turn.call.private_words()
        if any(_hidden(stated, private) or not stated_fact_irrelevant(stated, turn.frame)
               for stated in turn.call.stated()):
            return self._private(turn, DEPENDS_REASON)
        return None

    def _private(self, turn: VoiceTurn, reason: str) -> Verdict:
        turn.call.mark_private(turn.text)
        return Verdict(self.name, reason, (Counter.REFUSED_PRIVATE, Counter.INFERRED))
