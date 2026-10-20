"""Call state: what the agent remembers about one call, as structure, not transcript.

It replaces "send the last N raw turns": a follow-up after five "hold on"s still resolves,
because fillers never change it; a fact said at turn 2 ("I'm a premium member") still counts
at turn 40; and the agent's own words ("that hotel", "the second one") stay resolvable.
Only verified turn frames and the agent's replies update it. No I/O.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from .turn import Attribute, TurnFrame

TASKS = ("none", "searching", "booking", "ordering", "account_action")
IDENTITIES = ("anonymous", "identified", "verified")
MAX_FACTS = 10
MAX_MENTIONS = 10
MAX_STATED = 10
MAX_PRIVATE_WORDS = 64
# Every kept text (a fact, the last reply, the open question) is cut to this, so a thread's
# memory stays a few KB whatever a user sends or a store hands back.
MAX_TEXT = 1000


def _clean(text: Any) -> str:
    return " ".join(str(text)[:MAX_TEXT * 4].split())[:MAX_TEXT] if text is not None else ""


def _strings(value: Any) -> List[str]:
    """A saved list of strings, or nothing: damaged saved data never breaks a thread."""
    if not isinstance(value, (list, tuple)):
        return []
    return [_clean(v) for v in value if isinstance(v, str) and _clean(v)]


def word_digest(word: str) -> str:
    word = _clean(word).lower()
    return hashlib.sha256(word.encode("utf-8")).hexdigest()[:16] if word else ""


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
    # The reply language the caller asked for ("reply only in Hindi"), set only by that request.
    language: Optional[str] = None
    # What the caller told that a later answer depends on ("allergic peanuts"), as the turn's
    # words without names or long numbers: a shared question must carry them. Never sent anywhere.
    stated: List[str] = field(default_factory=list)
    # Hashes of words that identified the caller in turns that were not shared ("sarah",
    # "55512"): a shared answer holding one is refused. Hashed, so the words are not kept.
    private_words: List[str] = field(default_factory=list)
    # Hashes of what named the caller (a name given, an email, a long number): a shared question
    # saying one is never shared. Narrower than private_words, which only refuses answers.
    names: List[str] = field(default_factory=list)
    # Hashes of the specific words of facts the caller told (a place, a month, a number: "goa",
    # "december", "3"): a shared question must carry every one, or it stays private.
    details: List[str] = field(default_factory=list)

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

    def note_stated(self, turn: str) -> None:
        turn = _clean(turn)
        if turn and turn not in self.stated:
            self.stated.append(turn)
        self.stated = self.stated[-MAX_STATED:]

    def note_private(self, words: Iterable[str]) -> None:
        for word in words:
            digest = word_digest(word)
            if digest and digest not in self.private_words:
                self.private_words.append(digest)
        self.private_words = self.private_words[-MAX_PRIVATE_WORDS:]

    def is_private(self, word: str) -> bool:
        return word_digest(word) in self.private_words

    def note_names(self, words: Iterable[str]) -> None:
        for word in words:
            digest = word_digest(word)
            if digest and digest not in self.names:
                self.names.append(digest)
        self.names = self.names[-MAX_PRIVATE_WORDS:]

    def is_name(self, word: str) -> bool:
        return word_digest(word) in self.names

    def note_details(self, words: Iterable[str]) -> None:
        for word in words:
            digest = word_digest(word)
            if digest and digest not in self.details:
                self.details.append(digest)
        self.details = self.details[-MAX_PRIVATE_WORDS:]

    # --- saved with the chat thread ----------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """Everything, for the app's own store: a stateless chat server restores it per request."""
        return {
            "active_question": self.active_question,
            "active_kind": self.active_kind,
            "facts": list(self.facts),
            "agent_mentions": list(self.agent_mentions),
            "task": self.task,
            "attributes": {k: {"value": a.value, "normalised": a.normalised, "changes_answer": a.changes_answer}
                           for k, a in self.attributes.items()},
            "subject_focus": self.subject_focus,
            "identity": self.identity,
            "last_reply": self.last_reply,
            "language": self.language,
            "stated": list(self.stated),
            "private_words": list(self.private_words),
            "names": list(self.names),
            "details": list(self.details),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "CallState":
        """Rebuild from ``to_dict``. Anything missing or malformed starts empty; never raises."""
        data = data if isinstance(data, dict) else {}
        state = cls()
        state.active_question = _clean(data.get("active_question")) or None
        state.active_kind = _clean(data.get("active_kind")) or None
        state.facts = _strings(data.get("facts"))[-MAX_FACTS:]
        state.agent_mentions = _strings(data.get("agent_mentions"))[-MAX_MENTIONS:]
        state.start_task(_clean(data.get("task")))
        attributes = data.get("attributes")
        for name, raw in (attributes.items() if isinstance(attributes, dict) else ()):
            attr = Attribute.from_dict(raw)
            if attr is not None and name in ("segment", "region"):
                state.attributes[name] = attr
        state.subject_focus = _clean(data.get("subject_focus")) or "none"
        identity = _clean(data.get("identity")).lower()
        state.identity = identity if identity in IDENTITIES else "anonymous"
        state.last_reply = _clean(data.get("last_reply"))
        state.language = _clean(data.get("language")).lower()[:32] or None
        for turn in _strings(data.get("stated")):
            state.note_stated(turn)
        state.private_words = [d for d in _strings(data.get("private_words")) if len(d) == 16][-MAX_PRIVATE_WORDS:]
        state.names = [d for d in _strings(data.get("names")) if len(d) == 16][-MAX_PRIVATE_WORDS:]
        state.details = [d for d in _strings(data.get("details")) if len(d) == 16][-MAX_PRIVATE_WORDS:]
        return state

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
            "language": self.language,
        }

    def grounding_sources(self) -> List[str]:
        """Text the shared question may draw its words from, besides the turn itself."""
        out = [self.active_question or "", self.last_reply]
        out += self.facts + self.agent_mentions + self.stated  # the caller's own words count
        return [s for s in out if s]


__all__ = ["CallState", "TASKS", "IDENTITIES"]
