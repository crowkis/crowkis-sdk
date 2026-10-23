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

import re
import zlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .callstate import CallState
from .turn import DETAIL_TYPES, NOT_GENERAL_TYPES, TurnFrame

from .rules.chat_rule_set import ChatRuleSet
from .turns.chat_turn import ChatTurn
from .turns.routes import AGENT, PERSONAL, SHARED, TASK, TOOLS, URGENT  # noqa: F401 - re-exported

# Default expiry per question type, in seconds. None = until the knowledge version changes.
DEFAULT_TTL: Dict[str, Optional[int]] = {
    "policy": None,
    "how_to": None,
    "product_fact": 24 * 3600,
    "place_fact": 6 * 3600,
    "search": 3600,
    "other": 3600,
}

from .understanding.frame_words import (  # noqa: F401 - re-exported
    _FUNCTION,
    _WORD,
    _TOLD_TYPES,
    _NUMWORDS,
    _UNITS,
    _EMAIL,
    _PHONE,
    _LONG_DIGITS,
    _toks,
    _stem,
    _QUESTION_WORDS,
    _REFERRING,
    _CONTRACTION,
    _CLAUSE_START,
    _GENERIC_FACT,
    _looks_identifying,
)


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
        attrs = self._key_attributes(frame, state, question)
        # A language the caller asked for wins over the language this turn happens to be in.
        language = state.language or frame.language
        return Verdict(True, SHARED, [], question, attrs, self.build_key(question, attrs),
                       self.ttl.get(frame.question_type, self.ttl["other"]),
                       self.build_segment(attrs, language, told=self._tailoring(frame, state, question)))

    @staticmethod
    def _route_for(frame: TurnFrame) -> str:
        if frame.kind in ("personal", "sensitive"):
            return PERSONAL
        if frame.kind in ("live", "action"):
            return TOOLS
        return AGENT

    @staticmethod
    def _tailoring(frame: TurnFrame, state: CallState, question: str) -> Optional[str]:
        """What the question carries from what the caller told (their facts, the details of
        this turn): a short hash of those words, or None for a question anyone could ask.
        Two callers with a peanut allergy share answers; peanut and shellfish never do."""
        told = list(state.stated) + [f.split(":", 1)[-1] for f in state.facts if f.split(":", 1)[0] in _TOLD_TYPES]
        # In the question itself only a condition tailors it ("for someone with a peanut allergy");
        # a place, time or amount there is part of what anyone could ask.
        told += [e.text for e in frame.entities if e.type == "condition" and not e.identifying]
        told_stems = {_stem(w) for text in told for w in _toks(text) if w not in _FUNCTION}
        carried = sorted({_stem(w) for w in _toks(question) if w not in _FUNCTION} & told_stems)
        return format(zlib.crc32(" ".join(carried).encode()), "08x") if carried else None

    # --- the key ----------------------------------------------------------------------

    @staticmethod
    def _key_attributes(frame: TurnFrame, state: CallState, question: str) -> Dict[str, str]:
        attrs: Dict[str, str] = {}
        for name in ("segment", "region"):
            attr = frame.attributes.get(name)
            if attr is not None and attr.changes_answer:
                attrs[name] = attr.normalised
        # Location rule: a question about a named local place, or a search, always carries the
        # call's location, because many places share a name and results differ by city.
        if frame.question_type in ("place_fact", "search") and "region" not in attrs:
            region = frame.attributes.get("region") or state.attributes.get("region")
            if region is not None:
                attrs["region"] = region.normalised
        # What the question already says keeps it apart by itself ("the capital of France" is
        # not "the capital of Spain"); in the segment too it would only split equal questions.
        qwords = set(_toks(question))
        for name, value in list(attrs.items()):
            # The place itself, all of it, word for word: "goa" of "goa, india"; "new york" is not "new".
            words = [w for w in _toks(value.split(",")[0]) if w not in _FUNCTION]
            if words and all(w in qwords for w in words):
                del attrs[name]
        return attrs

    def build_key(self, question: str, attrs: Dict[str, str]) -> str:
        """The question alone: it is what is embedded and matched, so nothing else may be in
        its text. Version, language, place and tier go in the segment (``build_segment``)."""
        return " ".join(question.split())

    def build_segment(self, attrs: Dict[str, str], language: Optional[str], *, told: Optional[str] = None) -> str:
        """``kb=<version>;lang=<language>;region=...;segment=...;channel=<channel>[;told=1]``:
        one segment per knowledge version, reply language, place, tier and channel. A new
        knowledge version retires old answers at once. ``told=<hash>`` when the question carries
        facts the user told (an allergy, an age): "Is pad thai safe for someone with a peanut
        allergy?" is answered "avoid it", which is wrong for someone who asked only "is pad thai
        safe?", and a near match would serve it. Tailored answers only meet the same facts."""
        parts = [f"kb={self.knowledge_version}", f"lang={language or 'und'}"]
        parts += [f"{k}={attrs[k]}" for k in sorted(attrs)]
        parts.append(f"channel={self.channel}")
        if told:
            parts.append(f"told={told}")
        # A value can never add or change a field.
        parts = [p.split("=", 1)[0] + "=" + re.sub(r"[;=]", "_", p.split("=", 1)[1]) for p in parts]
        return ";".join(" ".join(p.split()) for p in parts)


__all__ = ["RuleChecker", "Verdict", "DEFAULT_TTL", "URGENT", "TASK", "SHARED", "PERSONAL", "TOOLS", "AGENT"]
