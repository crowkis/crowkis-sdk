"""Stage 3 rules (save): answers right for this caller only (identifiers, private words, values, claims)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns.voice.turn import ModelAnswer
from ...turns.values import Outcome, Verdict
from ...understanding.word_rules.private_words import _ACTION_CLAIM
from ...understanding.word_rules.follow_up import _unfinished
from ...understanding.word_rules.personal import _bare, _leaks, _repeats_identifier
from ...understanding.word_rules.answers import _repeats_prompt_details
from ...understanding.word_rules.text import _words


class CallerIdentifier:
    """An answer repeating a number or ID this caller said is never shared. Its model read only
    the question, so this can only come from an app that sent it the whole call."""

    name = "CallerIdentifier"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _repeats_identifier(answer.answer, answer.call.said_identifiers()):
            return None
        return Verdict(self.name, "kept to this call: the answer repeats a number or ID this caller said",
                       (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)


class PromptCallerDetails:
    """The model read a system prompt that names this caller, and its answer repeats that:
    right for this caller only, never a shared answer or shape."""

    name = "PromptCallerDetails"
    floor = True

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.instructions or not _repeats_prompt_details(
                answer.answer, answer.text, answer.instructions, answer.call.agent_key()):
            return None
        return Verdict(self.name, "kept to this call: the answer repeats a detail about the caller "
                                  "from the system prompt", (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)


# The VoicePrivateWord rule (stage 3, save; every voice session).
class VoicePrivateWord:
    """A word that identified the caller in a turn kept private ("Sarah",
    "55512") is never in a shared answer, unless the shared question itself has it."""

    name = "VoicePrivateWord"
    floor = True

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        asked = set(_words(answer.key or ""))
        private = answer.call.private_words()
        if not any(w not in asked and (w in private or _bare(w) in private) for w in _words(answer.answer)):
            return None
        return Verdict(self.name, "kept to this call: the answer holds a word that identified this caller",
                       (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)


class DeclaredValue:
    """An answer holding a value declared for this call is never shared."""

    name = "DeclaredValue"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _leaks(answer.answer, answer.call.values):
            return None
        return Verdict(self.name, "kept to this call: the answer contains a value declared for this call",
                       (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)


class PersonalTemplate:
    """An answer about the caller's own records is shared only as a shape with this call's
    declared values taken out; this rule says when it cannot be (the call was told something,
    the answer does not answer, the turn was cut off, or no shape could be made)."""

    name = "PersonalTemplate"
    floor = True
    REASON = "about this caller, with no declared value to make a shared answer shape from"

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_personal:
            return None
        if answer.call.tainted or answer.is_non_answer or _unfinished(answer.text):
            return self.refusal()
        return None

    def refusal(self) -> Verdict:
        """The verdict when no shared shape is made from a personal answer."""
        return Verdict(self.name, self.REASON, (), Outcome.PRIVATE)


# The VoiceActionClaim rule (stage 3, save; voice with an understander).
class VoiceActionClaim:
    """An answer saying something was done for this caller ("I have
    cancelled your order") is not shared."""

    name = "VoiceActionClaim"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _ACTION_CLAIM.search(answer.answer or ""):
            return None
        return Verdict(self.name, "kept to this call: the answer says something was done for this caller",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)
