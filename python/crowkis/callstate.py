"""Call state: what the agent remembers about one call, as structure, not transcript.

It replaces "send the last N raw turns": a follow-up after five "hold on"s still resolves,
because fillers never change it; a fact said at turn 2 ("I'm a premium member") still counts
at turn 40; and the agent's own words ("that hotel", "the second one") stay resolvable.
Only verified turn frames and the agent's replies update it. No I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .turn import Attribute, TurnFrame

TASKS = ("none", "searching", "booking", "ordering", "account_action")
IDENTITIES = ("anonymous", "identified", "verified")
MAX_FACTS = 10
MAX_MENTIONS = 10


def _clean(text: Any) -> str:
    return " ".join(str(text).split()) if text is not None else ""


@dataclass
class CallState:
    active_question: Optional[str] = None
    active_kind: Optional[str] = None
    facts: List[str] = field(default_factory=list)
    agent_mentions: List[str] = field(default_factory=list)
    task: str = "none"
    attributes: Dict[str, Attribute] = field(default_factory=dict)
    subject_focus: str = "none"
    identity: str = "anonymous"
    last_reply: str = ""

    # --- the agent's side -------------------------------------------------------------

    def note_agent_reply(self, text: str, mentions: Iterable[str] = (), task: Optional[str] = None) -> None:
        """Record what the agent just said: the reply, the things it named or offered, and the
        task it is running (set by the app, which knows when it starts collecting details)."""
        self.last_reply = _clean(text)
        for item in mentions:
            item = _clean(item)
            if item and item not in self.agent_mentions:
                self.agent_mentions.append(item)
        self.agent_mentions = self.agent_mentions[-MAX_MENTIONS:]
        if task is not None:
            self.start_task(task)

    def start_task(self, task: str) -> None:
        task = (task or "none").lower()
        self.task = task if task in TASKS else "none"

    def end_task(self) -> None:
        self.task = "none"

    def set_identity(self, identity: str) -> None:
        """Set by the app after its own checks; the cache never infers it."""
        identity = (identity or "").lower()
        if identity not in IDENTITIES:
            raise ValueError(f"identity must be one of {IDENTITIES}, got {identity!r}")
        self.identity = identity

    # --- the caller's side ------------------------------------------------------------

    def apply(self, frame: TurnFrame, *, shared: bool) -> None:
        """Update from a caller turn's frame once the rule checker has ruled on it.

        ``shared`` is the checker's verdict: only a verified general question becomes the
        active question that later follow-ups resolve against.
        """
        if frame.abstain:
            # The caller referred to something we cannot see: never let a later turn
            # resolve against a stale question instead. Checked first: a bare "what about
            # that?" with no details must still clear it.
            self.active_question = None
            self.active_kind = "dialogue"
            return
        if frame.is_pure_acknowledgement:
            return
        if frame.kind == "general" and shared and frame.question:
            self.active_question = frame.question
            self.active_kind = "general"
            if not frame.task_step:
                self.end_task()  # the caller moved on to a fresh question
        else:
            self.active_kind = frame.kind
        if frame.kind == "action" and self.task == "none":
            self.task = "account_action"
        if frame.subject in ("self", "other"):
            self.subject_focus = frame.subject
        for entity in frame.memorable:
            fact = f"{entity.type}: {entity.text}"
            if fact in self.facts:
                self.facts.remove(fact)
            self.facts.append(fact)
        self.facts = self.facts[-MAX_FACTS:]
        for name, attr in frame.attributes.items():
            if name in ("segment", "region"):
                self.attributes[name] = attr

    # --- what crosses to the server ---------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """The de-identified state sent with each turn. No caller transcript is included;
        identity stays in the app."""
        return {
            "active_question": self.active_question,
            "active_kind": self.active_kind,
            "facts": list(self.facts),
            "agent_mentions": list(self.agent_mentions),
            "task": self.task,
            "attributes": {k: {"value": a.value, "normalised": a.normalised} for k, a in self.attributes.items()},
            "last_reply": self.last_reply,
        }

    def grounding_sources(self) -> List[str]:
        """Text the shared question may draw its words from, besides the turn itself."""
        out = [self.active_question or "", self.last_reply]
        out += self.facts + self.agent_mentions
        return [s for s in out if s]


__all__ = ["CallState", "TASKS", "IDENTITIES"]
