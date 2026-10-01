"""One conversation's cache decisions, with no I/O.

For every turn a ``Conversation`` decides:

  plan()    whether to look the turn up, under which key, and what the model must
            read on a miss: the question alone, the question before it plus this
            one (a follow-up), or the whole conversation (a personal turn)
  served()  what to say when the cache answered (a shape is filled with this
            conversation's values)
  settle()  after the model answered: whether its answer may be saved, as what,
            and under which key

The app does its own reads and writes, sync or async, in any payload format, and
asks the conversation for every decision. So channels with very different
pipelines (a Pipecat voice agent, an HTTP chat backend) follow one set of rules.
``VoiceSession`` is such an app; the rules themselves live in ``crowkis.rules``.

The safety rule underneath: an answer may be shared only when the model saw
nothing but its cache key, so nothing else the caller said (a name, a plan,
"pretend refunds are unlimited") can end up inside it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .rules import (
    _CONTEXT_BOUND_THRESHOLD,
    _SLOT,
    _abstract,
    _fill,
    _is_context_dependent,
    _is_non_answer,
    _is_personal,
    _leaks,
    _normalise,
)

Message = Dict[str, str]

# TurnPlan.action
FILLER = "filler"   # answer with plan.filler: no lookup, no model
LOOKUP = "lookup"   # look plan.key up; on a miss, ask the model
MODEL = "model"     # ask the model straight away (plan.reason says why)

# Saving.outcome
SAVED = "saved"             # write saving.text under saving.key, shared
TEMPLATE = "template"       # write saving.text (an answer shape with slots) under saving.key
KEPT = "kept"               # shareable-looking, but the model saw more than the key, or it holds a value
PRIVATE = "private"         # a personal turn with no shape to save
NON_ANSWER = "non_answer"   # only questions back, or it leads with "I'm not sure"
INTERRUPTED = "interrupted" # the turn was cancelled (barge-in) before the answer arrived
NOT_SAVED = "not_saved"     # empty answer, or a follow-up with nothing before it


@dataclass(frozen=True)
class TurnPlan:
    """What to do with one turn. Plain data; the app acts on it."""

    said: str
    action: str
    reason: str  # filler | lookup | empty | short | personal_no_values | no_prior_turn | unplanned
    key: Optional[str]  # cache key for both the lookup and the save; None when none can be built
    personal: bool
    template: bool  # look up / save an answer shape filled with this conversation's values
    threshold: Optional[float]  # near-exact bar for a turn that only means something after the last
    messages: Optional[List[Message]]  # what the model reads on a miss; None = the whole conversation
    shareable: bool  # the model's answer may be shared with later callers
    filler: Optional[str] = None

    @property
    def model_sees(self) -> str:
        if self.messages is None:
            return "whole conversation"
        return "question" if len(self.messages) == 1 else "question + previous"


@dataclass(frozen=True)
class Saving:
    """What to do with the model's answer to a planned turn."""

    outcome: str
    key: Optional[str] = None
    text: Optional[str] = None
    template: bool = False

    @property
    def write(self) -> bool:
        """Whether the app should write ``text`` under ``key`` now."""
        return self.outcome in (SAVED, TEMPLATE)


class Conversation:
    """The decisions for one call or chat thread. Not thread-safe: one turn at a time."""

    def __init__(
        self,
        *,
        min_words: int = 3,
        values: Optional[Dict[str, object]] = None,
        fillers: Optional[Dict[str, str]] = None,
        max_turns: Optional[int] = None,
    ) -> None:
        if min_words < 1:
            raise ValueError(f"min_words must be at least 1, got {min_words}")
        if max_turns is not None and max_turns < 1:
            raise ValueError(f"max_turns must be at least 1, got {max_turns}")
        self.min_words = min_words
        # How many caller turns of history a whole-conversation model call carries.
        # None keeps everything; a long chat thread should set it.
        self.max_turns = max_turns
        self.values: Dict[str, str] = {}
        self.transcript: List[Message] = []
        self._fillers: Dict[str, str] = {}
        self._mark = 0
        self._open = False
        self._cancelled = False
        if values:
            self.set_values(**values)
        if fillers:
            self.register_fillers(fillers)

    # --- this conversation's facts ------------------------------------------------------

    def set_values(self, **values: object) -> None:
        """The caller's own values (order id, eta ...) that fill a shared answer shape."""
        for name, value in values.items():
            if value is None:
                self.values.pop(name, None)
            else:
                self.values[name] = str(value)

    def register_filler(self, trigger: str, response: str) -> None:
        key = _normalise(trigger)
        if not key:
            raise ValueError("a filler trigger must contain something to match on")
        if not (response or "").strip():
            raise ValueError("a filler response must not be empty")
        self._fillers[key] = response

    def register_fillers(self, pairs: Dict[str, str]) -> None:
        for trigger, response in pairs.items():
            self.register_filler(trigger, response)

    # --- one turn -------------------------------------------------------------------------

    def plan(self, said: str) -> TurnPlan:
        """Decide what to do with what the caller just said. Opens the turn."""
        self._mark = len(self.transcript)
        self._open = True
        self._cancelled = False
        text = (said or "").strip()
        messages, shareable = self._model_messages(said, text)
        base = dict(said=said, key=self._context_key(said, text), messages=messages, shareable=shareable)

        if not text:
            return TurnPlan(action=MODEL, reason="empty", personal=False, template=False, threshold=None, **base)
        filler = self._fillers.get(_normalise(text))
        if filler is not None:
            return TurnPlan(action=FILLER, reason="filler", personal=False, template=False, threshold=None,
                            filler=filler, **base)
        if len(text.split()) < self.min_words:
            return TurnPlan(action=MODEL, reason="short", personal=False, template=False, threshold=None, **base)
        personal = _is_personal(text)
        if personal and not self.values:
            return TurnPlan(action=MODEL, reason="personal_no_values", personal=True, template=False,
                            threshold=None, **base)
        if base["key"] is None:
            return TurnPlan(action=MODEL, reason="no_prior_turn", personal=personal, template=False,
                            threshold=None, **base)
        return TurnPlan(
            action=LOOKUP, reason="lookup", personal=personal, template=personal,
            threshold=_CONTEXT_BOUND_THRESHOLD if _is_context_dependent(text) else None, **base,
        )

    def unplanned(self, said: str) -> TurnPlan:
        """A plan for an answer that arrived with no decision behind it: never shared."""
        text = (said or "").strip()
        return TurnPlan(said=said, action=MODEL, reason="unplanned", key=self._context_key(said, text),
                        personal=_is_personal(text) if text else False, template=False, threshold=None,
                        messages=None, shareable=False)

    def served(self, plan: TurnPlan, cached: str) -> Optional[str]:
        """The cache answered: what to say. None when a shape has a slot this conversation
        cannot fill (then ask the model instead). The turn stays open, so a barge-in
        over the spoken answer can still cancel it."""
        answer = cached
        if plan.template:
            answer = _fill(cached, self.values)
            if answer is None:
                return None
        self.transcript.append({"role": "user", "content": plan.said})
        self.transcript.append({"role": "assistant", "content": answer})
        return answer

    def model_messages(self, plan: TurnPlan, system: Optional[str] = None) -> List[Message]:
        """Exactly what the model must read for this turn, ``system`` first."""
        if plan.messages is not None:
            messages = list(plan.messages)
        else:
            messages = self._history() + [{"role": "user", "content": plan.said}]
        if system:
            messages = [{"role": "system", "content": system}] + messages
        return messages

    def settle(self, plan: TurnPlan, answer: str) -> Saving:
        """The model answered ``plan``: remember the turn, and decide what may be saved."""
        if self._cancelled:
            return Saving(INTERRUPTED)
        self._open = False
        self.transcript.append({"role": "user", "content": plan.said})
        self.transcript.append({"role": "assistant", "content": answer})
        if not (answer and answer.strip()) or plan.key is None:
            return Saving(NOT_SAVED)
        if _is_non_answer(answer):
            return Saving(NON_ANSWER)
        if plan.personal:
            shaped = _abstract(answer, self.values)
            if self.values and _SLOT.search(shaped) and not _leaks(shaped, self.values):
                return Saving(TEMPLATE, key=plan.key, text=shaped, template=True)
            return Saving(PRIVATE)
        if not plan.shareable or _leaks(answer, self.values):
            return Saving(KEPT)
        return Saving(SAVED, key=plan.key, text=answer)

    def keep_private(self, said: str, answer: str) -> bool:
        """Remember a turn that is never cached (a model that holds the whole
        conversation itself). False when the turn was cancelled."""
        if self._cancelled:
            return False
        self._open = False
        self.transcript.append({"role": "user", "content": said})
        self.transcript.append({"role": "assistant", "content": answer})
        return True

    def cancel(self) -> bool:
        """Abandon the open turn (barge-in): it leaves no trace and nothing is saved."""
        if not self._open:
            return False
        self._open = False
        self._cancelled = True
        del self.transcript[self._mark:]
        return True

    # --- internals ------------------------------------------------------------------------

    def _model_messages(self, said: str, text: str):
        if len(text.split()) < self.min_words or _is_personal(text):
            return None, False
        if not _is_context_dependent(text):
            return [{"role": "user", "content": said}], True
        prior = self._prior_user()
        if prior is None or _is_personal(prior):
            return None, False
        return [{"role": "user", "content": prior}, {"role": "user", "content": said}], True

    def _history(self) -> List[Message]:
        if self.max_turns is None:
            return list(self.transcript)
        return list(self.transcript[-2 * self.max_turns:])

    def _prior_user(self) -> Optional[str]:
        for turn in reversed(self.transcript):
            if turn["role"] == "user":
                return turn["content"]
        return None

    def _context_key(self, said: str, text: str) -> Optional[str]:
        if not _is_context_dependent(text):
            return said
        prior = self._prior_user()
        if prior is None:
            return None
        return f"{prior} || {said}"


__all__ = [
    "Conversation", "TurnPlan", "Saving",
    "FILLER", "LOOKUP", "MODEL",
    "SAVED", "TEMPLATE", "KEPT", "PRIVATE", "NON_ANSWER", "INTERRUPTED", "NOT_SAVED",
]
