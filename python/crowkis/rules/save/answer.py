"""Save rules: when the model's answer to a turn is not shared with later callers.

A family of small rules, in the order an answer is checked. Each verdict says what happened
to the answer (``outcome``) in the words ``record()`` reports."""

from __future__ import annotations

from typing import Optional

from ...turns import ModelAnswer, Verdict
from ...understanding.word_rules import _leaks, _repeats_identifier, _repeats_prompt_details, _unfinished

KEPT = "kept"
PRIVATE = "private"
NON_ANSWER = "non_answer"
NOT_SAVED = "not_saved"


class EmptyAnswer:
    """A model that said nothing has nothing to save."""

    name = "EmptyAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if (answer.answer or "").strip():
            return None
        return Verdict(self.name, "the model returned an empty answer", ("empty_answers",), NON_ANSWER)


class NoKey:
    """A follow-up with no earlier turn to key it on cannot be saved."""

    name = "NoKey"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.key is not None:
            return None
        return Verdict(self.name, "a follow-up with no earlier turn to key it on", (), NOT_SAVED)


class ToolResult:
    """An answer built from a tool's result stays in the call."""

    name = "ToolResult"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.private:
            return None
        return Verdict(self.name, "kept to this call: the answer was built from a tool's result",
                       ("not_shareable",), KEPT)


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
                                  "from the system prompt", ("not_shareable",), PRIVATE)


class PersonalTemplate:
    """An answer about the caller's own records is shared only as a shape with this call's
    declared values taken out; this rule says when it cannot be (the call was told something,
    the answer does not answer, the turn was cut off, or no shape could be made)."""

    name = "PersonalTemplate"
    floor = False
    REASON = "about this caller, with no declared value to make a shared answer shape from"

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_personal:
            return None
        if answer.call.tainted or answer.is_non_answer or _unfinished(answer.text):
            return self.refusal()
        return None

    def refusal(self) -> Verdict:
        """The verdict when no shared shape is made from a personal answer."""
        return Verdict(self.name, self.REASON, (), PRIVATE)


class TaintedCall:
    """Once the caller told the call something an answer may depend on, nothing more is shared."""

    name = "TaintedCall"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.call.tainted:
            return None
        return Verdict(self.name, "kept to this call: the caller told it something the answer may depend on",
                       ("not_shareable",), KEPT)


class NotShareable:
    """An answer decide() did not let be shared (the model read more than the question) stays in the call."""

    name = "NotShareable"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.cacheable:
            return None
        return Verdict(self.name, "kept to this call: the answer depends on what this caller said",
                       ("not_shareable",), KEPT)


class DeclaredValue:
    """An answer holding a value declared for this call is never shared."""

    name = "DeclaredValue"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _leaks(answer.answer, answer.call.values):
            return None
        return Verdict(self.name, "kept to this call: the answer contains a value declared for this call",
                       ("not_shareable",), PRIVATE)


class CallerIdentifier:
    """An answer repeating a number or ID this caller said is never shared. Its model read only
    the question, so this can only come from an app that sent it the whole call."""

    name = "CallerIdentifier"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not _repeats_identifier(answer.answer, answer.call.said_identifiers()):
            return None
        return Verdict(self.name, "kept to this call: the answer repeats a number or ID this caller said",
                       ("not_shareable",), PRIVATE)


class NonAnswer:
    """An answer that asks back or does not answer is not saved."""

    name = "NonAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_non_answer:
            return None
        return Verdict(self.name, "not saved: the answer asks back or does not answer", ("not_shareable",), NON_ANSWER)
