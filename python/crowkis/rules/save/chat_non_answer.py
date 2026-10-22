"""The ChatNonAnswer rule (stage 3, save; Chat, "non_answer")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.word_rules import _is_non_answer


class ChatNonAnswer:
    """An answer that asks back or does not answer is not saved."""

    name = "ChatNonAnswer"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not _is_non_answer(answer.text):
            return None
        return Verdict(self.name, "non_answer")
