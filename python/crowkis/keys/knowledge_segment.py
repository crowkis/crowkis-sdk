"""KnowledgeSegment: the segment a channel's answers are looked up and saved in, per knowledge version."""

from __future__ import annotations

import re
import zlib
from typing import TYPE_CHECKING, Dict, Optional, Sequence, Tuple

from ..state.call_state import CallState
from ..understanding.frame_words import _FUNCTION, _TOLD_TYPES, _stem, _toks
from ..understanding.turn_frame import TurnFrame

if TYPE_CHECKING:  # the turns package imports these keys, so a runtime import would be a cycle
    from ..turns.values import Channel

# A value can never add or change a field of the segment.
_FIELD_BREAKERS = re.compile(r"[;=\s]+")


def key(question: str) -> str:
    """The question alone: it is what is embedded and matched, so nothing else may be in its text."""
    return " ".join(question.split())


def follow_up_key(said: str, chain: Optional[Sequence[str]] = None) -> str:
    """A voice turn's key: its words as said, or the earlier turns it leans on joined to it."""
    return " || ".join([*chain, said]) if chain else said


def segment(fields: Sequence[Tuple[str, str]]) -> str:
    """``name=value;...``: a value can never add or change a field, and whitespace is collapsed."""
    return ";".join(" ".join(f"{name}={re.sub(r'[;=]', '_', value)}".split()) for name, value in fields)


def key_attributes(frame: TurnFrame, state: CallState, question: str) -> Dict[str, str]:
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


def told(frame: TurnFrame, state: CallState, question: str) -> Optional[str]:
    """What the question carries from what the caller told (their facts, the details of
    this turn): a short hash of those words, or None for a question anyone could ask.
    Two callers with a peanut allergy share answers; peanut and shellfish never do."""
    heard = list(state.stated) + [f.split(":", 1)[-1] for f in state.facts if f.split(":", 1)[0] in _TOLD_TYPES]
    # In the question itself only a condition tailors it ("for someone with a peanut allergy");
    # a place, time or amount there is part of what anyone could ask.
    heard += [e.text for e in frame.entities if e.type == "condition" and not e.identifying]
    told_stems = {_stem(w) for text in heard for w in _toks(text) if w not in _FUNCTION}
    carried = sorted({_stem(w) for w in _toks(question) if w not in _FUNCTION} & told_stems)
    return format(zlib.crc32(" ".join(carried).encode()), "08x") if carried else None


class KnowledgeSegment:
    """``kb=<version>;channel=<name>``: answers made with one understanding (its prompt, its model) and
    knowledge version only ever meet each other, so switching understanders, or the knowledge behind
    the answers, is a deliberate new version, never a silent mix. Chat builds the same fields in its
    own, longer segment (RuleChecker.build_segment)."""

    def __init__(self, version: str, channel: "Channel") -> None:
        self.version = _FIELD_BREAKERS.sub("_", str(version).strip()) or "1"
        self.channel = channel

    @property
    def segment(self) -> str:
        return segment([("kb", self.version), ("channel", self.channel.name)])
