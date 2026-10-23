"""The ChatCallerIdentifier rule (stage 3, save; Chat)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.word_rules import _identifiers


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
