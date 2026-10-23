"""The ChatToolResult rule (stage 3, save; Chat)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict


class ChatToolResult:
    """Voice's ToolResult on Chat (v4): an answer the app built from a tool's result
    (``record_answer(..., private=True)``) stays in the chat."""

    name = "ChatToolResult"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        if not answer.private:
            return None
        return Verdict(self.name, "tool_result")
