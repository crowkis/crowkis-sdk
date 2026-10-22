"""RuleChain: the rules of one stage, in order."""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, Tuple

from ..client import CrowkisError
from ..turns import Verdict
from .rule import Rule


class FloorRuleLocked(CrowkisError, ValueError):
    """A floor rule was asked to be turned off without the explicit unsafe flag."""


class UnknownRule(CrowkisError, ValueError):
    """A rule was named that the rule set does not have."""


def rule_names(names: Sequence[str]) -> Tuple[str, ...]:
    """The names as a tuple; one string is refused, as it would match by its letters."""
    if isinstance(names, str):
        raise TypeError("rule names are a list of names, not one string")
    return tuple(names)


class RuleChain:
    """Chain of Responsibility: the rules of one stage, run in order; the first objection
    wins and names its rule."""

    def __init__(self, rules: Iterable[Rule]) -> None:
        self._rules: Tuple[Rule, ...] = tuple(rules)

    @property
    def names(self) -> Tuple[str, ...]:
        return tuple(rule.name for rule in self._rules)

    def first_objection(self, subject: Any) -> Optional[Verdict]:
        """The first rule's objection to ``subject``, or None when every rule lets it through."""
        for rule in self._rules:
            verdict = rule.check(subject)
            if verdict is not None:
                return verdict
        return None

    def without(self, names: Sequence[str], *, unsafe: bool = False) -> "RuleChain":
        """This chain with the named rules turned off. A floor rule stays on unless ``unsafe``."""
        names = rule_names(names)
        locked = [rule.name for rule in self._rules if rule.name in names and rule.floor]
        if locked and not unsafe:
            raise FloorRuleLocked(f"floor rules cannot be turned off without unsafe=True: {', '.join(locked)}")
        return RuleChain(rule for rule in self._rules if rule.name not in names)
