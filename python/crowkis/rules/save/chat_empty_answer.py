"""The ChatEmptyAnswer rule (stage 3, save; Chat, "empty")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict


class ChatEmptyAnswer:
    """An empty answer has nothing to save."""

    name = "ChatEmptyAnswer"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if answer.text:
            return None
        return Verdict(self.name, "empty")
