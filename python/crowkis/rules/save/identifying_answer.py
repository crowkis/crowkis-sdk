"""The IdentifyingAnswer rule (stage 3, save; Chat, "identifying")."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict
from ...understanding.answer_patterns import _EMAIL, _LONG_DIGITS


class IdentifyingAnswer:
    """An answer holding an email, a long digit run, or a detail the frame tagged as identifying is
    never shared."""

    name = "IdentifyingAnswer"
    floor = True

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        text = answer.text
        tagged = answer.frame is not None and any(t.lower() in text.lower() for t in answer.frame.identifying_texts)
        if not (_EMAIL.search(text) or _LONG_DIGITS.search(text) or tagged):
            return None
        return Verdict(self.name, "identifying")
