"""The AttributeNotInKey rule (stage 3, save; Chat, "attribute_not_in_key")."""

from __future__ import annotations

import re
from typing import Optional

from ...turns.chat_answer import ChatAnswer
from ...turns.verdict import Verdict


class AttributeNotInKey:
    """An answer that names one of this chat's attributes (a region, a tier) which did not enter the
    key would reach users it does not fit. A value the question itself says ("the capital of
    France") is part of what was asked."""

    name = "AttributeNotInKey"
    floor = False

    def check(self, answer: ChatAnswer) -> Optional[Verdict]:
        verdict = answer.verdict
        for name, attr in answer.state.attributes.items():
            pattern = r"\b" + re.escape(attr.value) + r"\b" if attr.value else None
            if name not in verdict.attributes and pattern and re.search(pattern, answer.text, re.I) \
                    and not re.search(pattern, verdict.question or "", re.I):
                return Verdict(self.name, "attribute_not_in_key")
        return None
