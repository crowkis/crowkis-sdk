"""The VoicePrivateWord rule (stage 3, save; voice with an understander)."""

from __future__ import annotations

from typing import Optional

from ...runtime.stats import Counter
from ...turns import ModelAnswer, Outcome, Verdict
from ...understanding.word_rules import _words


class VoicePrivateWord:
    """Chat's PrivateWord on voice (v4): a word that identified the caller in a turn kept private ("Sarah",
    "55512") is never in a shared answer, unless the shared question itself has it."""

    name = "VoicePrivateWord"
    floor = True

    def check(self, answer: ModelAnswer) -> Optional[Verdict]:
        asked = set(_words(answer.key or ""))
        private = answer.call.private_words()
        if not any(w not in asked and w in private for w in _words(answer.answer)):
            return None
        return Verdict(self.name, "kept to this call: the answer holds a word that identified this caller",
                       (Counter.NOT_SHAREABLE,), Outcome.PRIVATE)
