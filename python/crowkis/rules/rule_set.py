"""RuleSet: every rule a voice session runs, grouped by where in a turn they run."""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Dict, Mapping, Optional, Sequence

from ..turns.values import CachedAnswer
from ..turns.values import Checked
from ..turns.values import Hit
from ..turns.voice.turn import VoiceTurn
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
from .question import (
    CallContextTaint,
    CutOff,
    EmptyTurn,
    FollowUpWithoutContext,
    OwnRecords,
    PrivateChain,
    RegisteredFiller,
    TooShort,
    VoiceStatedFacts,
)
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
    VoiceActionClaim,
    VoicePrivateWord,
)


@dataclass(frozen=True)
class RuleSet:
    """The rules of the three SDK stages, as chains in the order a turn meets them.

    Stage 1 (question) runs ``before_filler``, then ``filler`` (a registered filler answers the turn
    itself), then ``question``. Stage 2 (hit) runs ``hit`` on a hit. Stage 3 (save) runs ``answer_given``, then
    ``before_sharing`` once the turn is in the transcript, then ``personal`` for a personal
    turn (whose answer may become a shared shape) or ``sharing`` for any other.

    The set is also TurnCore's question and hit check for a voice call (``check_question``,
    ``check_hit``): those two stages are only its rules."""

    before_filler: RuleChain
    filler: RuleChain
    question: RuleChain
    hit: RuleChain
    answer_given: RuleChain
    before_sharing: RuleChain
    personal: PersonalTemplate
    sharing: RuleChain

    @classmethod
    def voice(cls, fillers: Optional[Mapping[str, str]] = None) -> "RuleSet":
        """The voice defaults: today's rules, in today's order; ``fillers`` is the session's live map
        of registered fillers (none when not given)."""
        return cls(
            before_filler=RuleChain([EmptyTurn()]),
            filler=RuleChain([RegisteredFiller({} if fillers is None else fillers)]),
            question=RuleChain([CallContextTaint(), TooShort(), CutOff(), OwnRecords(), FollowUpWithoutContext(),
                                PrivateChain()]),
            hit=RuleChain([ConfidenceBar(), TemplateSlotMissing(), PiiPlaceholder(), DifferentQuestion(),
                           ShortTurnUnvouched(), CommitmentRewording(), ScreenOnlyAnswer()]),
            answer_given=RuleChain([EmptyAnswer()]),
            before_sharing=RuleChain([NoKey(), ToolResult(), PromptCallerDetails()]),
            personal=PersonalTemplate(),
            sharing=RuleChain([TaintedCall(), NotShareable(), DeclaredValue(), CallerIdentifier(), VoiceActionClaim(),
                               NonAnswer()]),
        )

    @classmethod
    def understood(cls, fillers: Optional[Mapping[str, str]] = None) -> "RuleSet":
        """The rules of a voice session with an understander plugged in (v4): StatedFacts, which keeps
        only the turns whose answer a stated fact may change, replaces the call-wide CallContextTaint, and the
        save check gains Chat's PrivateWord and ActionClaim (the merged save check)."""
        rules = cls.voice(fillers)
        sharing = RuleChain([TaintedCall(), NotShareable(), DeclaredValue(), CallerIdentifier(), VoicePrivateWord(),
                             VoiceActionClaim(), NonAnswer()])
        return replace(rules, question=rules.question.replacing("CallContextTaint", VoiceStatedFacts()), sharing=sharing)

    def check_question(self, turn: VoiceTurn) -> Checked:
        """Stage 1: the first objection of ``before_filler``, ``filler`` (a filler answers the turn
        itself), then ``question``."""
        for chain in (self.before_filler, self.filler, self.question):
            verdict = chain.first_objection(turn)
            if verdict is not None:
                return Checked(turn, verdict)
        return Checked(turn)

    def check_hit(self, turn: VoiceTurn, hit: Dict[str, Any], started: float) -> Checked:
        """Stage 2: the hit as the hit rules read it, and their first objection."""
        cached = CachedAnswer(turn, Hit.from_agent(hit), started)
        return Checked(cached, self.hit.first_objection(cached))

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
