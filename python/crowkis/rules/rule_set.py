"""RuleSet: every rule a voice session runs, grouped by where in a turn they run."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Sequence

from .chain import FloorRuleLocked, RuleChain, UnknownRule, rule_names
from .hit import (
    CommitmentRewording,
    ConfidenceBar,
    DifferentQuestion,
    PiiPlaceholder,
    ScreenOnlyAnswer,
    ShortTurnUnvouched,
    TemplateSlotMissing,
)
from .question import CallContextTaint, CutOff, EmptyTurn, FollowUpWithoutContext, OwnRecords, PrivateChain, TooShort
from .save import (
    CallerIdentifier,
    DeclaredValue,
    EmptyAnswer,
    NoKey,
    NonAnswer,
    NotShareable,
    PersonalTemplate,
    PromptCallerDetails,
    TaintedCall,
    ToolResult,
)


@dataclass(frozen=True)
class RuleSet:
    """The rules of the three SDK stages, as chains in the order a turn meets them.

    Stage 1 (question) runs ``before_filler`` and then ``question``, around the registered
    fillers. Stage 2 (hit) runs ``hit`` on a hit. Stage 3 (save) runs ``answer_given``, then
    ``before_sharing`` once the turn is in the transcript, then ``personal`` for a personal
    turn (whose answer may become a shared shape) or ``sharing`` for any other."""

    before_filler: RuleChain
    question: RuleChain
    hit: RuleChain
    answer_given: RuleChain
    before_sharing: RuleChain
    personal: PersonalTemplate
    sharing: RuleChain

    @classmethod
    def voice(cls) -> "RuleSet":
        """The voice defaults: today's rules, in today's order."""
        return cls(
            before_filler=RuleChain([EmptyTurn()]),
            question=RuleChain([CallContextTaint(), TooShort(), CutOff(), OwnRecords(), FollowUpWithoutContext(),
                                PrivateChain()]),
            hit=RuleChain([ConfidenceBar(), TemplateSlotMissing(), PiiPlaceholder(), DifferentQuestion(),
                           ShortTurnUnvouched(), CommitmentRewording(), ScreenOnlyAnswer()]),
            answer_given=RuleChain([EmptyAnswer()]),
            before_sharing=RuleChain([NoKey(), ToolResult(), PromptCallerDetails()]),
            personal=PersonalTemplate(),
            sharing=RuleChain([TaintedCall(), NotShareable(), DeclaredValue(), CallerIdentifier(), NonAnswer()]),
        )

    def without(self, names: Sequence[str], *, unsafe: bool = False) -> "RuleSet":
        """These rules with the named ones turned off; a floor rule stays on unless ``unsafe``.
        The personal-answer rule is never turned off: it decides when an answer about the caller's
        own records is shared. A name the set does not have is refused."""
        names = rule_names(names)
        chains = {f.name: getattr(self, f.name) for f in fields(self) if isinstance(getattr(self, f.name), RuleChain)}
        known = {name for chain in chains.values() for name in chain.names} | {self.personal.name}
        unknown = [name for name in names if name not in known]
        if unknown:
            raise UnknownRule(f"no such rule: {', '.join(unknown)}")
        if self.personal.name in names:
            raise FloorRuleLocked(f"{self.personal.name} cannot be turned off: it decides when an answer about "
                                  "the caller's own records is shared")
        return replace(self, **{name: chain.without(names, unsafe=unsafe) for name, chain in chains.items()})
