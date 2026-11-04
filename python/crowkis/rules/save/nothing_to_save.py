"""Stage 3 rules (save): nothing to share (empty or non-answers, tool results, no key, a tainted call)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns.voice.turn import ModelAnswer
from ...turns.values import Outcome, Verdict
from ...turns.chat.turn import ChatAnswer
from ...understanding.word_rules import _is_non_answer


class EmptyAnswer:
    """A model that said nothing has nothing to save."""

    name = "EmptyAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if (answer.answer or "").strip():
            return None
        return Verdict(self.name, "the model returned an empty answer", (Counter.EMPTY_ANSWERS,), Outcome.NON_ANSWER)


# The ChatEmptyAnswer rule (stage 3, save; Chat, "empty").
class ChatEmptyAnswer:
    """An empty answer has nothing to save."""

    name = "ChatEmptyAnswer"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if answer.text:
            return None
        return Verdict(self.name, "empty")


class NonAnswer:
    """An answer that asks back or does not answer is not saved."""

    name = "NonAnswer"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.is_non_answer:
            return None
        return Verdict(self.name, "not saved: the answer asks back or does not answer", (Counter.NOT_SHAREABLE,), Outcome.NON_ANSWER)


# The ChatNonAnswer rule (stage 3, save; Chat, "non_answer").
class ChatNonAnswer:
    """An answer that asks back or does not answer is not saved."""

    name = "ChatNonAnswer"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not _is_non_answer(answer.text):
            return None
        return Verdict(self.name, "non_answer")


class ToolResult:
    """An answer built from a tool's result stays in the call."""

    name = "ToolResult"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.private:
            return None
        return Verdict(self.name, "kept to this call: the answer was built from a tool's result",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)


# The ChatToolResult rule (stage 3, save; Chat).
class ChatToolResult:
    """Voice's ToolResult on Chat (v4): an answer the app built from a tool's result
    (``record_answer(..., private=True)``) stays in the chat."""

    name = "ChatToolResult"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not answer.private:
            return None
        return Verdict(self.name, "tool_result")


class NoKey:
    """A follow-up with no earlier turn to key it on cannot be saved."""

    name = "NoKey"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.key is not None:
            return None
        return Verdict(self.name, "a follow-up with no earlier turn to key it on", (), Outcome.NOT_SAVED)


class NotShareable:
    """An answer decide() did not let be shared (the model read more than the question) stays in the call."""

    name = "NotShareable"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if answer.cacheable:
            return None
        return Verdict(self.name, "kept to this call: the answer depends on what this caller said",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)


class TaintedCall:
    """Once the caller told the call something an answer may depend on, nothing more is shared."""

    name = "TaintedCall"
    floor = False

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        if not answer.call.tainted:
            return None
        return Verdict(self.name, "kept to this call: the caller told it something the answer may depend on",
                       (Counter.NOT_SHAREABLE,), Outcome.KEPT)
