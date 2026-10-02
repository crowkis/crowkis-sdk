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
  V7 an answer-relevant detail of the turn missing from the key
  V8 tier/location enter the key only when they change the answer
  V9 a step of a task in progress (booking, ordering...) goes to the agent, never shared
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .callstate import CallState
from .turn import DETAIL_TYPES, NOT_GENERAL_TYPES, TurnFrame

URGENT, TASK, SHARED, PERSONAL, TOOLS, AGENT = "urgent", "task", "shared", "personal", "tools", "agent"

# Default expiry per question type, in seconds. None = until the knowledge version changes.
DEFAULT_TTL: Dict[str, Optional[int]] = {
    "policy": None,
    "how_to": None,
    "product_fact": 24 * 3600,
    "place_fact": 6 * 3600,
    "search": 3600,
    "other": 3600,
}

# Words any question may use without them appearing in the turn: grammar, question words and
# ordinary request verbs. Not a list about meaning; it never decides kind or privacy.
_FUNCTION = frozenset("""a an the and or but if of to in on at for from by with about into over under after before
during than then so as is are was were be been being am do does did done doing have has had having can could will
would shall should may might must i you we they it its this that these those there here what which who whom whose
when where why how much many long often any some each every all no not yes my your our their me us them per same
other another own just only also more most less least very please get got getting give make take need want use used
using apply applying offer offers offered available availability allowed allow include includes included work works
working cost costs charge charged charges price pricing fee fees option options way ways happen happens like
differ different one two three four five six seven eight nine ten first second third time times day days
tell find found look looking show give know serve serves served recommend suggest""".split())

_WORD = re.compile(r"[a-z0-9]+")
_NUMWORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
             "eight": "8", "nine": "9", "ten": "10"}
_UNITS = r"(rupees?|rs|inr|dollars?|usd|items?|people|persons?|days?|weeks?|months?|years?|hours?|kg|gb|inch(es)?|%)"
_EMAIL = re.compile(r"\S+@\S+|\bat\s+(gmail|yahoo|hotmail|outlook)\b", re.I)
_PHONE = re.compile(r"\b\d{10}\b|\(\d{3}\)\s*\d{3}-\d{4}")
_LONG_DIGITS = re.compile(r"\d(?:[\s-]?\d){4,}")


def _toks(text: str) -> List[str]:
    return [_NUMWORDS.get(w, w) for w in _WORD.findall((text or "").lower())]


def _stem(word: str) -> str:
    """Crude, symmetric word-form normaliser: expires/expire, removing/remove, qualifies/qualify."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > 4 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    if len(word) > 3 and word.endswith("e"):
        word = word[:-1]
    if len(word) > 3 and word.endswith(("y", "i")):
        word = word[:-1]
    return word


def _looks_identifying(question: str) -> bool:
    if _EMAIL.search(question) or _PHONE.search(question):
        return True
    low = question.lower()
    for match in _LONG_DIGITS.finditer(low):
        if not re.match(r"\s*" + _UNITS, low[match.end(): match.end() + 12]):
            return True  # a long number that is not a quantity: an order ID, account, phone...
    return False


@dataclass
class Verdict:
    shared: bool
    route: str
    reasons: List[str] = field(default_factory=list)
    question: Optional[str] = None
    attributes: Dict[str, str] = field(default_factory=dict)  # attributes that entered the key
    key: Optional[str] = None
    ttl: Optional[int] = None


class RuleChecker:
    """Applies V1-V9 to a frame and builds the key for a shareable turn.

    ``confidence_floor`` should be calibrated per business on real calls (a fixed number is
    only the starting point). ``ttl`` maps question types to expiry in seconds.
    """

    def __init__(self, *, confidence_floor: float = 0.6, ttl: Optional[Dict[str, Optional[int]]] = None,
                 knowledge_version: str = "1") -> None:
        if not 0.0 <= confidence_floor <= 1.0:
            raise ValueError(f"confidence_floor must be in 0..1, got {confidence_floor}")
        self.confidence_floor = confidence_floor
        self.ttl = dict(DEFAULT_TTL, **(ttl or {}))
        self.knowledge_version = str(knowledge_version)

    # --- the rules --------------------------------------------------------------------

    def check(self, frame: TurnFrame, turn: str, state: CallState) -> Verdict:
        reasons: List[str] = []
        if frame.urgent:
            return Verdict(False, URGENT, ["V1_urgent"])
        if frame.task_step or self._answers_agent_during_task(turn, state):
            return Verdict(False, TASK, ["V9_task_step"])
        if frame.abstain or frame.confidence < self.confidence_floor:
            reasons.append("V2_uncertain")
        if frame.kind != "general" or frame.subject != "none":
            reasons.append("V3_not_general")
        if any(e.type in NOT_GENERAL_TYPES for e in frame.entities):
            reasons.append("V4_about_someone")
        question = frame.question
        if not question:
            reasons.append("V3_no_question")
        if reasons:
            return Verdict(False, self._route_for(frame), reasons)

        low = question.lower()
        if any(t.lower() in low for t in frame.identifying_texts) or _looks_identifying(question):
            reasons.append("V5_identifying")
        added = self._ungrounded(question, turn, state)
        if added:
            reasons.append("V6_ungrounded:" + ",".join(added[:3]))
        lost = self._lost_detail(frame, question)
        if lost:
            reasons.append("V7_lost:" + lost)
        if reasons:
            return Verdict(False, AGENT, reasons)

        attrs = self._key_attributes(frame, state)
        return Verdict(True, SHARED, [], question, attrs, self.build_key(question, attrs),
                       self.ttl.get(frame.question_type, self.ttl["other"]))

    @staticmethod
    def _answers_agent_during_task(turn: str, state: CallState) -> bool:
        """While a task is running, a reply to the agent's own question is a step of it."""
        return state.task != "none" and state.last_reply.rstrip().endswith("?") and "?" not in (turn or "")

    @staticmethod
    def _route_for(frame: TurnFrame) -> str:
        if frame.kind in ("personal", "sensitive"):
            return PERSONAL
        if frame.kind in ("live", "action"):
            return TOOLS
        return AGENT

    @staticmethod
    def _ungrounded(question: str, turn: str, state: CallState) -> List[str]:
        source = set(_toks(turn))
        for text in state.grounding_sources():
            source.update(_toks(text))
        stems = {_stem(w) for w in source}
        return [w for w in _toks(question) if w not in _FUNCTION and w not in source and _stem(w) not in stems]

    @staticmethod
    def _lost_detail(frame: TurnFrame, question: str) -> Optional[str]:
        qstems = {_stem(w) for w in _toks(question)}
        attr_text = " ".join(f"{a.value} {a.normalised}" for a in frame.attributes.values()).lower()
        for e in frame.entities:
            if e.answer_relevant and not e.identifying and e.type in DETAIL_TYPES:
                words = [w for w in _toks(e.text) if w not in _FUNCTION]
                if words and not any(_stem(w) in qstems for w in words) and not any(w in attr_text for w in words):
                    return e.text
        return None

    # --- the key ----------------------------------------------------------------------

    @staticmethod
    def _key_attributes(frame: TurnFrame, state: CallState) -> Dict[str, str]:
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
        return attrs

    def build_key(self, question: str, attrs: Dict[str, str]) -> str:
        """``[kb=<version>; region=...; segment=...] <question>``: one key per meaning, tier,
        place and knowledge version. A new knowledge version retires old answers at once."""
        parts = [f"kb={self.knowledge_version}"] + [f"{k}={attrs[k]}" for k in sorted(attrs)]
        return "[" + "; ".join(parts) + "] " + " ".join(question.split())


__all__ = ["RuleChecker", "Verdict", "DEFAULT_TTL", "URGENT", "TASK", "SHARED", "PERSONAL", "TOOLS", "AGENT"]
