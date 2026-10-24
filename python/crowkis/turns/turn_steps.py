"""The parts TurnCore's fixed steps call: one small interface per step, each with a voice and a chat
implementation that the facades (the composition roots) pick."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from .checked import Checked, LookedUp
from .verdict import Verdict


class CallSettings(Protocol):
    """The call's settings a lookup reads, live: an app may change them between turns."""

    @property
    def agent(self) -> Any:
        """The agent lookups go through."""

    @property
    def serve_above(self) -> float:
        """The confidence a cached answer needs to be served."""

    @property
    def latency_budget_ms(self) -> Optional[float]:
        """The lookup's budget (None: wait as long as the cache takes)."""


class Pairing(Protocol):
    """Which turn an answer belongs to."""

    def open(self) -> int:
        """A turn is being decided: its number."""

    def settle(self, answered: Any) -> Checked:
        """The answer paired with its turn, or the objection that drops it (the caller moved on)."""


class EarlyAnswers(Protocol):
    """Answers a turn gets without the cache or the model."""

    def before_reading(self, said: str, turn: int) -> Optional[Any]:
        """The channel's result for turn number ``turn``, answered before it is read, or None."""

    def after_check(self, checked: Checked) -> Optional[Any]:
        """The channel's result for a turn the question check stopped and something other than the
        model answers (a filler, an app's hook), or None."""


class TurnReader(Protocol):
    """How a turn is understood."""

    def read(self, said: str, turn: int) -> Any:
        """Turn number ``turn``, read: what the question and hit checks see."""


class QuestionCheck(Protocol):
    """Stage 1: whether a turn may be looked up and shared."""

    def check_question(self, turn: Any) -> Checked:
        """The turn as checked (keyed, for a chat) and the first objection, if any."""


class HitCheck(Protocol):
    """Stage 2: whether a hit may be served."""

    def check_hit(self, turn: Any, hit: Dict[str, Any], started: float) -> Checked:
        """The hit as the hit rules read it and the objection to serving it, if any."""


class Report(Protocol):
    """Adapter: the channel's public results, counts and events for what the core found."""

    def to_model(self, checked: Checked) -> Any:
        """The question check stopped the turn: the model answers with the whole call."""

    def missed(self, checked: Checked, looked: LookedUp) -> Any:
        """No hit may be served: the model answers the turn."""

    def served(self, checked: Checked, looked: LookedUp) -> Any:
        """A hit is served (``looked.cached``)."""

    def kept(self, verdict: Verdict) -> Any:
        """An answer is not saved (dropped or kept out of the shared cache): the outcome."""

    def refused(self, error: Exception) -> Any:
        """The write of an answer failed: the outcome."""

    def recorded(self, answered: Any, outcome: Any) -> Any:
        """Whatever happened to an answer: counted or reported as the channel does; the outcome."""


class Saving(Protocol):
    """Stage 3 and the write."""

    def check(self, answered: Any) -> Checked:
        """The answer as the save rules read it, and the objection to saving it, if any."""

    def write(self, answer: Any) -> Any:
        """Share the answer and write it, within the bounded write: the outcome."""
