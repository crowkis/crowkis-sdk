"""ChatRuleSet: the rules a Chat session runs on the understanding model's frame of a turn."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Sequence

from .chain import RuleChain, UnknownRule, rule_names
from .question import (
    AboutSomeone,
    IdentifyingDetails,
    LostDetail,
    NoQuestion,
    NotGeneral,
    StatedFacts,
    TaskStep,
    UncertainFrame,
    Ungrounded,
    UnresolvedReference,
    UrgentTurn,
)

V7 = "V7_LostOrDropped"


@dataclass(frozen=True)
class ChatRuleSet:
    """Chat's question rules (V1-V10), in the three groups the rule checker runs: ``decisive``
    (the first objection decides alone and names the route: urgent, a task step), ``frame``
    (every objection is reported; the frame is not a general question) and ``question`` (every
    objection is reported; the stand-alone question is not safe as a key). Within ``question``,
    V7 is one objection: a lost detail of this turn, else a dropped fact the caller stated."""

    decisive: RuleChain
    frame: RuleChain
    question: RuleChain

    @classmethod
    def chat(cls, confidence_floor: float) -> "ChatRuleSet":
        """Chat's rules today, in today's order."""
        return cls(
            decisive=RuleChain([UrgentTurn(), TaskStep()]),
            frame=RuleChain([UncertainFrame(confidence_floor), NotGeneral(), AboutSomeone(), NoQuestion()]),
            question=RuleChain([IdentifyingDetails(), Ungrounded(), UnresolvedReference(),
                                RuleChain([LostDetail(), StatedFacts()], name=V7)]),
        )

    def without(self, names: Sequence[str], *, unsafe: bool = False) -> "ChatRuleSet":
        """These rules with the named ones turned off; a floor rule stays on unless ``unsafe``."""
        names = rule_names(names)
        chains = {f.name: getattr(self, f.name) for f in fields(self)}
        known = {name for chain in chains.values() for name in chain.all_names}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise UnknownRule(f"no such rule: {', '.join(unknown)}")
        return replace(self, **{name: chain.without(names, unsafe=unsafe) for name, chain in chains.items()})
