"""RuleChain: the rules of one stage, in order."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional, Sequence, Tuple

from ..client import CrowkisError
from ..turns.values import Verdict
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


def _holds_floor(rule: Rule) -> bool:
    """A floor rule, or a chain with a floor rule anywhere inside it."""
    if rule.floor:
        return True
    return isinstance(rule, RuleChain) and any(_holds_floor(inner) for inner in rule._rules)


class RuleChain:
    """Chain of Responsibility: the rules of one stage, run in order; the first objection
    wins and names its rule. ``all_objections`` runs every rule instead (Chat reports each
    objection). A chain is itself a rule (Composite): its ``check`` is its first objection, so a
    group where one objection is enough can sit inside a chain that collects them all."""

    def __init__(self, rules: Iterable[Rule], *, name: str = "", floor: bool = False) -> None:
        self._rules: Tuple[Rule, ...] = tuple(rules)
        self.name = name
        self.floor = floor

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

    def check(self, subject: Any) -> Optional[Verdict]:
        """This chain as one rule: its first objection."""
        return self.first_objection(subject)

    def all_objections(self, subject: Any) -> List[Verdict]:
        """Every rule's objection to ``subject``, in order."""
        found = []
        for rule in self._rules:
            verdict = rule.check(subject)
            if verdict is not None:
                found.append(verdict)
        return found

    @property
    def all_names(self) -> Tuple[str, ...]:
        """Every rule's name, the rules of chains inside this one included."""
        found = []
        for rule in self._rules:
            found.append(rule.name)
            if isinstance(rule, RuleChain):
                found.extend(rule.all_names)
        return tuple(found)

    def without(self, names: Sequence[str], *, unsafe: bool = False) -> "RuleChain":
        """This chain with the named rules turned off, in chains inside it too. A floor rule stays
        on unless ``unsafe``."""
        names = rule_names(names)
        locked = [rule.name for rule in self._rules if rule.name in names and _holds_floor(rule)]
        if locked and not unsafe:
            raise FloorRuleLocked(f"floor rules cannot be turned off without unsafe=True: {', '.join(locked)}")
        kept = [rule.without(names, unsafe=unsafe) if isinstance(rule, RuleChain) else rule
                for rule in self._rules if rule.name not in names]
        return RuleChain(kept, name=self.name, floor=self.floor)

    def replacing(self, name: str, rule: Rule) -> "RuleChain":
        """This chain with the rule called ``name`` swapped for ``rule``, in the same place. A floor
        rule is never swapped; a name the chain does not have is refused."""
        if name not in self.names:
            raise UnknownRule(f"no such rule: {name}")
        if any(old.name == name and _holds_floor(old) for old in self._rules):
            raise FloorRuleLocked(f"a floor rule cannot be replaced: {name}")
        return RuleChain([rule if old.name == name else old for old in self._rules], name=self.name, floor=self.floor)
