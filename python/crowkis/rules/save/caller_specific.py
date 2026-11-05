"""Stage 3 rules (save): answers right for this caller only (identifiers, private words, values, claims)."""

from __future__ import annotations

import re
from typing import Optional

from ...runtime.stats import Counter
from ...turns.voice.turn import ModelAnswer
from ...turns.values import Outcome, Verdict
from ...turns.chat.turn import ChatAnswer
from ...understanding.word_rules.chat import _ACTION_CLAIM, _ANSWER_EMAIL, _ANSWER_LONG_DIGITS
from ...understanding.word_rules.follow_up import _unfinished
from ...understanding.word_rules.personal import _bare, _identifiers, _leaks, _repeats_identifier
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


# The ChatCallerIdentifier rule (stage 3, save; Chat).
class ChatCallerIdentifier:
    """Voice's CallerIdentifier on Chat (v4): an answer repeating an ID-like value the user said anywhere
    in this chat (an order number, an email, a long digit group), even in a turn that was shared, is
    never shared, unless the shared question itself has it."""

    name = "ChatCallerIdentifier"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        asked = _identifiers([answer.verdict.question or ""])
        if not any(value not in asked and answer.state.said_identifier(value) for value in _identifiers([answer.text])):
            return None
        return Verdict(self.name, "caller_identifier")


# The IdentifyingAnswer rule (stage 3, save; Chat, "identifying").
class IdentifyingAnswer:
    """An answer holding an email, a long digit run, or a detail the frame tagged as identifying is
    never shared."""

    name = "IdentifyingAnswer"
    floor = True

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        text = answer.text
        tagged = answer.frame is not None and any(t.lower() in text.lower() for t in answer.frame.identifying_texts)
        if not (_ANSWER_EMAIL.search(text) or _ANSWER_LONG_DIGITS.search(text) or tagged):
            return None
        return Verdict(self.name, "identifying")


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


# The ChatPromptDetails rule (stage 3, save; Chat, "prompt_detail").
class ChatPromptDetails:
    """An answer repeating a detail the system prompt gives about this user ("Hi Asha!") is right
    for this user only, never a shared answer."""

    name = "ChatPromptDetails"
    floor = True

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not answer.instructions or not _repeats_prompt_details(
                answer.text, answer.verdict.question or "", answer.instructions, answer.prompt_key):
            return None
        return Verdict(self.name, "prompt_detail")


# The PrivateWord rule (stage 3, save; Chat, "private_word").
class PrivateWord:
    """A word that identified the user in a turn that was not shared ("Sarah", "55512") is never in
    a shared answer, unless the shared question itself has it."""

    name = "PrivateWord"
    floor = True

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        asked = set(_words(answer.verdict.question or ""))
        if not any(w not in asked and (answer.state.is_private(w) or answer.state.is_private(_bare(w))) for w in _words(answer.text)):
            return None
        return Verdict(self.name, "private_word")


# The VoicePrivateWord rule (stage 3, save; every voice session).
class VoicePrivateWord:
    """Chat's PrivateWord on voice (v4): a word that identified the caller in a turn kept private ("Sarah",
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


# The ActionClaim rule (stage 3, save; Chat, "action_claim").
class ActionClaim:
    """An answer saying something was done for this user ("I have cancelled your order") is not shared."""

    name = "ActionClaim"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not _ACTION_CLAIM.search(answer.text):
            return None
        return Verdict(self.name, "action_claim")


# The VoiceActionClaim rule (stage 3, save; voice with an understander).
class VoiceActionClaim:
    """Chat's ActionClaim on voice (v4): an answer saying something was done for this caller ("I have
    cancelled your order") is not shared."""

    name = "VoiceActionClaim"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _ACTION_CLAIM.search(answer.answer or ""):
            return None
        return Verdict(self.name, "kept to this call: the answer says something was done for this caller",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)


# The AttributeNotInKey rule (stage 3, save; Chat, "attribute_not_in_key").
class AttributeNotInKey:
    """An answer that names one of this chat's attributes (a region, a tier) which did not enter the
    key would reach users it does not fit. A value the question itself says ("the capital of
    France") is part of what was asked."""

    name = "AttributeNotInKey"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        verdict = answer.verdict
        for name, attr in answer.state.attributes.items():
            pattern = r"\b" + re.escape(attr.value) + r"\b" if attr.value else None
            if name not in verdict.attributes and pattern and re.search(pattern, answer.text, re.I) \
                    and not re.search(pattern, verdict.question or "", re.I):
                return Verdict(self.name, "attribute_not_in_key")
        return None
