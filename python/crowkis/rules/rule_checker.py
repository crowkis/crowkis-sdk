"""The rule checker and the key builder (turn understanding v2.2, part 2).

The model says what a turn is; these fixed rules decide what may be shared and under which
key. They check the frame's structure (entity types, where each word came from, the call's
task) and never decide meaning from word lists. Anything uncertain is not shared. No I/O.

Rules
  V1 urgent                                   -> urgent route, never shared
  V2 abstained, or confidence below the floor -> not shared
  V3 not general, or about someone            -> not shared
  V4 an owned record / own purchase / other person contradicts "general"
  V5 an identifying entity, an email, a phone number or an ID-like digit run in the key
  V6 a content word of the key that is not in the turn or the call state (grounding)
  V7 an answer-relevant detail of the turn missing from the key; and, in fixed code, a fact
     the caller stated in this chat (an allergy, an age, a trip) missing from the question
  V8 tier/location enter the key only when they change the answer
  V9 a step of a task in progress (booking, ordering...) goes to the agent, never shared
  V10 a follow-up whose key still says "it", "there", "that"... and names nothing from the chat
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..keys import key, key_attributes, segment, told
from ..state.call_state import CallState
from ..understanding.turn_frame import TurnFrame

from .chat_rule_set import ChatRuleSet
from ..turns.chat.turn import ChatTurn
from ..turns.results import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT  # noqa: F401 - re-exported

# Default expiry per question type, in seconds. None = until the knowledge version changes.
DEFAULT_TTL: Dict[str, Optional[int]] = {
    "policy": None,
    "how_to": None,
    "product_fact": 24 * 3600,
    "place_fact": 6 * 3600,
    "search": 3600,
    "other": 3600,
}


@dataclass
class Verdict:
    shared: bool
    route: str
    reasons: List[str] = field(default_factory=list)
    question: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)  # attributes that entered the key
    key: Optional[str] = None
    ttl: Optional[int] = None
    # SEGMENT the answer is stored and looked up under: knowledge version, reply language,
    # region and tier, channel. Answers in different segments never meet.
    segment: Optional[str] = None


class RuleChecker:
    """Applies V1-V10 (ChatRuleSet) to a frame and builds the key for a shareable turn.

    ``confidence_floor`` should be calibrated per business on real calls (a fixed number is
    only the starting point). ``ttl`` maps question types to expiry in seconds.
    """

    def __init__(self, *, confidence_floor: float = 0.6, ttl: Optional[Dict[str, Optional[int]]] = None,
                 knowledge_version: str = "1", channel: str = "chat") -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError(f"confidence_floor must be in 0..1, got {confidence_floor}")
        self.confidence_floor = confidence_floor
        self.ttl = dict(DEFAULT_TTL, **(ttl or {}))
        self.knowledge_version = str(knowledge_version)
        self.channel = " ".join(str(channel).split()).lower() or "chat"
        # V1-V10 as rules (rules/question), in the three groups this checker runs; rebuilt if the
        # public confidence_floor is changed later, as the old inline check read it on every turn.
        self._rules = ChatRuleSet.chat(self.confidence_floor)
        self._rules_floor = self.confidence_floor

    # --- the rules --------------------------------------------------------------------

    def check(self, frame: TurnFrame, turn: str, state: CallState) -> Verdict:
        if self._rules_floor != self.confidence_floor:
            self._rules = ChatRuleSet.chat(self.confidence_floor)
            self._rules_floor = self.confidence_floor
        chat_turn = ChatTurn(frame, turn, state)
        decisive = self._rules.decisive.first_objection(chat_turn)
        if decisive is not None:
            return Verdict(False, decisive.route, [decisive.reason])
        reasons = [v.reason for v in self._rules.frame.all_objections(chat_turn)]
        if reasons:
            return Verdict(False, self._route_for(frame), reasons)
        reasons = [v.reason for v in self._rules.question.all_objections(chat_turn)]
        if reasons:
            return Verdict(False, AGENT, reasons)

        question = frame.question
        attrs = key_attributes(frame, state, question)
        # A language the caller asked for wins over the language this turn happens to be in.
        language = state.language or frame.language
        return Verdict(True, SHARED, [], question, attrs, self.build_key(question, attrs),
                       self.ttl.get(frame.question_type, self.ttl["other"]),
                       self.build_segment(attrs, language, told=told(frame, state, question)))

    @staticmethod
    def _route_for(frame: TurnFrame) -> str:
        if frame.kind in ("personal", "sensitive"):
            return PERSONAL
        if frame.kind in ("live", "action"):
            return TOOLS
        return AGENT

    # --- the key ----------------------------------------------------------------------

    def build_key(self, question: str, attrs: Dict[str, str]) -> str:
        """The question alone: it is what is embedded and matched, so nothing else may be in
        its text. Version, language, place and tier go in the segment (``build_segment``)."""
        return key(question)

    def build_segment(self, attrs: Dict[str, str], language: Optional[str], *, told: Optional[str] = None) -> str:
        """``kb=<version>;lang=<language>;region=...;segment=...;channel=<channel>[;told=1]``:
        one segment per knowledge version, reply language, place, tier and channel. A new
        knowledge version retires old answers at once. ``told=<hash>`` when the question carries
        facts the user told (an allergy, an age): "Is pad thai safe for someone with a peanut
        allergy?" is answered "avoid it", which is wrong for someone who asked only "is pad thai
        safe?", and a near match would serve it. Tailored answers only meet the same facts."""
        fields = [("kb", self.knowledge_version), ("lang", language or "und")]
        fields += [(k, attrs[k]) for k in sorted(attrs)]
        fields.append(("channel", self.channel))
        if told:
            fields.append(("told", told))
        return segment(fields)


__all__ = ["RuleChecker", "Verdict", "DEFAULT_TTL", "URGENT", "TASK", "SHARED", "PERSONAL", "TOOLS", "AGENT"]
