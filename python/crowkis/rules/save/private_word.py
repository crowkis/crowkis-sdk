"""The PrivateWord rule (stage 3, save; Chat, "private_word")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.word_rules import _words


class PrivateWord:
    """A word that identified the user in a turn that was not shared ("Sarah", "55512") is never in
    a shared answer, unless the shared question itself has it."""

    name = "PrivateWord"
    floor = True

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        asked = set(_words(answer.verdict.question or ""))
        if not any(w not in asked and answer.state.is_private(w) for w in _words(answer.text)):
            return None
        return Verdict(self.name, "private_word")
