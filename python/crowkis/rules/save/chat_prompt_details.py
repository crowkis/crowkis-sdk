"""The ChatPromptDetails rule (stage 3, save; Chat, "prompt_detail")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.word_rules import _repeats_prompt_details


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
