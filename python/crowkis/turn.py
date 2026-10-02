"""The turn frame: what turn understanding says about one caller turn.

A model (on the server, or an interim adapter) reads the caller's turn, the agent's last
reply and the call's state, and returns a frame. Everything downstream (the rule checker,
the key builder, the router, the call state) works on this structure, never on the raw
words. Parsing is fail-closed: anything missing or malformed reads as "not shareable".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

KINDS = ("general", "personal", "live", "action", "dialogue", "chitchat", "sensitive", "unclear")
SUBJECTS = ("none", "self", "other")
QUESTION_TYPES = ("policy", "how_to", "product_fact", "place_fact", "search", "other")

# Entity types whose text identifies a person: never allowed in a shared key.
IDENTIFYING_TYPES = frozenset({"person_name", "id_number", "contact", "address", "payment", "date_of_birth"})
# Entity types that make a turn about someone in particular, whatever its kind says.
NOT_GENERAL_TYPES = frozenset({"owned_record", "own_purchase", "other_person"})
# Non-identifying details worth remembering for later turns ("condition: damaged").
DETAIL_TYPES = frozenset({"product", "plan_product", "condition", "time", "quantity", "place"})


def _text(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in ("true", "yes", "1")
    return bool(value)


@dataclass(frozen=True)
class Entity:
    text: str
    type: str
    identifying: bool
    answer_relevant: bool

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entity":
        etype = _text(data.get("type")).lower() or "topic"
        # The type decides identifying-ness; a model saying otherwise is overruled.
        identifying = etype in IDENTIFYING_TYPES or _bool(data.get("identifying"))
        return cls(text=_text(data.get("text")), type=etype, identifying=identifying,
                   answer_relevant=_bool(data.get("answer_relevant")))


@dataclass(frozen=True)
class Attribute:
    """A tier or location. Open values; ``changes_answer`` decides whether it enters the key."""

    value: str
    normalised: str
    changes_answer: bool

    @classmethod
    def from_dict(cls, data: Any) -> Optional["Attribute"]:
        if isinstance(data, str):
            data = {"value": data}
        if not isinstance(data, dict):
            return None
        value = _text(data.get("value")).lower()
        if not value or value == "none":
            return None
        normalised = _text(data.get("normalised") or data.get("normalized")).lower() or value
        return cls(value=value, normalised=normalised, changes_answer=_bool(data.get("changes_answer")))


@dataclass(frozen=True)
class TurnFrame:
    kind: str
    urgent: bool
    subject: str
    task_step: bool
    confidence: float
    abstain: bool
    entities: List[Entity] = field(default_factory=list)
    attributes: Dict[str, Attribute] = field(default_factory=dict)
    uses_state: bool = False
    question: Optional[str] = None
    question_type: str = "other"

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "TurnFrame":
        """Read a model's output. Unknown or missing fields resolve to the safe side."""
        data = data if isinstance(data, dict) else {}
        kind = _text(data.get("kind")).lower()
        kind = kind if kind in KINDS else "unclear"
        subject = _text(data.get("subject")).lower()
        subject = subject if subject in SUBJECTS else ("none" if kind == "general" else "self")
        try:
            confidence = min(1.0, max(0.0, float(data.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0
        entities = [Entity.from_dict(e) for e in data.get("entities") or [] if isinstance(e, dict)]
        attributes = {}
        for name, raw in (data.get("attributes") or {}).items():
            attr = Attribute.from_dict(raw)
            if attr is not None:
                attributes[str(name).lower()] = attr
        question = _text(data.get("question"))
        qtype = _text(data.get("question_type")).lower()
        return cls(
            kind=kind,
            urgent=_bool(data.get("urgent")),
            subject=subject,
            task_step=_bool(data.get("task_step")),
            confidence=confidence,
            abstain=_bool(data.get("abstain")),
            entities=entities,
            attributes=attributes,
            uses_state=_bool(data.get("uses_state")),
            question=question if question and question != "-" else None,
            question_type=qtype if qtype in QUESTION_TYPES else "other",
        )

    @property
    def identifying_texts(self) -> List[str]:
        return [e.text for e in self.entities if e.identifying and e.text]

    @property
    def details(self) -> List[Entity]:
        """Non-identifying, answer-relevant details worth carrying to later turns."""
        return [e for e in self.entities
                if e.type in DETAIL_TYPES and e.answer_relevant and not e.identifying and e.text]

    @property
    def memorable(self) -> List[Entity]:
        """Non-identifying details a later turn may refer back to ("Park Winters", "the Pro plan"),
        whether or not they changed this turn's answer. Names, IDs and contacts never qualify."""
        return [e for e in self.entities
                if (e.type in DETAIL_TYPES or e.type == "topic") and not e.identifying and e.text]

    @property
    def is_pure_acknowledgement(self) -> bool:
        """Thanks, "okay", "hold on": turns that must not change the call's state. A greeting that
        also names a place or a tier ("Hi, I'm planning dinner at Park Winters") is not one."""
        if self.kind not in ("chitchat", "dialogue"):
            return False
        return not self.memorable and not self.attributes and not self.task_step and not self.uses_state


__all__ = ["TurnFrame", "Entity", "Attribute", "KINDS", "IDENTIFYING_TYPES", "NOT_GENERAL_TYPES",
           "DETAIL_TYPES", "QUESTION_TYPES"]
