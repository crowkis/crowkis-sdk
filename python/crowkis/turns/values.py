"""The turn core's value objects: a turn's verdicts, what the cache and the model said to it, a hit, the channel."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import Any, Dict, Optional, TYPE_CHECKING, Tuple, Union

from ..understanding.word_rules.answers import _fill

if TYPE_CHECKING:
    from ..runtime.stats import Counter

class Outcome(str, Enum):
    """The words callers see for an answer: ``decision.not_stored`` and the save rule's outcome on voice.
    A ``str`` enum, so each one compares, hashes, prints and serialises as its word."""

    SAVED = "saved"
    TEMPLATE = "template"
    KEPT = "kept"
    PRIVATE = "private"
    NON_ANSWER = "non_answer"
    NOT_SAVED = "not_saved"
    INTERRUPTED = "interrupted"
    NOT_SHARED = "not_shared"
    CANCELLED = "cancelled"
    STALE = "stale"
    SLOW_WRITE = "slow_write"
    REFUSED = "refused"

    def __str__(self) -> str:
        return self.value

    def __format__(self, spec: str) -> str:
        return format(self.value, spec)


class RecordedOutcome(str):
    """An ``Outcome`` as voice's record() reports it: the word, plus ``why`` an answer was not stored
    and the ``rule`` that decided it. A ``str``, because callers (the adapters, ``decision.stored``)
    compare it with the word and put it in reports."""

    why: str
    rule: Optional[str]

    def __new__(cls, outcome: Outcome, why: str = "", rule: Optional[str] = None) -> "RecordedOutcome":
        recorded = super().__new__(cls, str(outcome))
        recorded.why = why
        recorded.rule = rule
        return recorded


@dataclass(frozen=True)
class Verdict:
    """What a rule says when it objects.

    ``rule`` names the rule (in decisions, logs and ``stats()``), ``reason`` says why in words,
    ``counts`` are the session counters it adds to (``runtime.stats.Counter``),
    ``outcome`` is, for a save rule, what happened to the answer (an ``Outcome``), and
    ``route`` is, for a rule that decides alone, where the turn goes ("urgent", "task", "filler"),
    and ``answer`` is what to say at once when the rule answers the turn itself (a filler).
    """

    rule: str
    reason: str
    counts: Tuple[Union["Counter", str], ...] = ()
    outcome: Optional[str] = None
    route: Optional[str] = None
    answer: Optional[str] = None


@dataclass(frozen=True)
class Checked:
    """A step's subject (the turn, the answer) as the next step reads it, and the objection that
    stops the turn there, if any."""

    subject: Any
    objection: Optional[Verdict] = None


@dataclass(frozen=True)
class LookedUp:
    """The cache's raw ``hit`` for a turn (None when there was none in time), the hit as the hit
    rules read it (``cached``, None when no hit was checked), and the objection that sends the turn
    to the model instead, if any."""

    hit: Optional[Dict[str, Any]]
    cached: Any = None
    objection: Optional[Verdict] = None


CACHE_ROUTE = "cache"


@dataclass(frozen=True)
class Hit:
    """The agent's answer to a lookup: its route ("cache" when confident enough to speak), the answer
    text, the confidence, and the flags the server's decision engine set (an exact match, vouched for,
    a commitment such as a price or a policy)."""

    route: str
    answer: Optional[str]
    confidence: float
    exact: bool = False
    vouched: bool = False
    commitment: bool = False
    unjudged: bool = False  # a reworded match the server's engine has not judged yet

    @classmethod
    def from_agent(cls, hit: Dict[str, Any]) -> "Hit":
        """Built once from Agent.ask's result."""
        return cls(route=hit["route"], answer=hit.get("answer"), confidence=hit.get("confidence", 0.0),
                   exact=bool(hit.get("exact")), vouched=bool(hit.get("vouched")),
                   commitment=bool(hit.get("commitment")), unjudged=bool(hit.get("unjudged")))

    @property
    def is_confident(self) -> bool:
        return self.route == CACHE_ROUTE


class CachedAnswer:
    """What the cache returned for a turn: a voice ``VoiceTurn``. ``started`` is when the lookup began
    (``time.monotonic()``)."""

    def __init__(self, turn: Any, hit: Hit, started: float) -> None:
        self.turn = turn
        self.hit = hit
        self.started = started

    @cached_property
    def answer(self) -> Optional[str]:
        """The text to speak: for a personal turn, the shared answer shape filled with this
        call's values, or None when a slot has no value. Read only for a confident hit."""
        if self.turn.is_personal:
            return _fill(self.hit.answer, self.turn.call.values)
        return self.hit.answer


@dataclass(frozen=True)
class Channel:
    """A capability profile. Rules read these fields and never branch on the channel's name.

    ``isolates_context``: the model can be given only the question. ``budget_ms``: the lookup budget
    the factories use. ``understand_budget_ms``: how long a plugged-in classifier and rewriter may
    take on a turn before the word rules read it instead. ``audio``: answers have cached clips.
    ``spoken``: answers are read aloud, so screen-only answers are refused. ``saves_answers``: the
    channel writes answers itself. Today the rules read ``spoken`` and the factories the budgets;
    ``isolates_context``, ``audio`` and ``saves_answers`` describe the channel for the merged core (P5)."""

    name: str
    isolates_context: bool
    budget_ms: int
    audio: bool
    spoken: bool
    saves_answers: bool
    understand_budget_ms: int = 250

    @classmethod
    def of(cls, channel: Union["Channel", str]) -> "Channel":
        """A channel, or the profile with that name ("voice", "chat", "realtime")."""
        if isinstance(channel, Channel):
            return channel
        try:
            return CHANNELS[str(channel).strip().lower()]
        except KeyError:
            raise ValueError(f"channel must be one of {sorted(CHANNELS)} or a Channel, got {channel!r}") from None


VOICE = Channel("voice", isolates_context=True, budget_ms=250, audio=True, spoken=True, saves_answers=True)
CHAT = Channel("chat", isolates_context=True, budget_ms=1000, audio=False, spoken=False, saves_answers=True)
REALTIME = Channel("realtime", isolates_context=False, budget_ms=250, audio=False, spoken=True, saves_answers=False)

CHANNELS: Dict[str, Channel] = {channel.name: channel for channel in (VOICE, CHAT, REALTIME)}
