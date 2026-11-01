"""SessionCall: the call a VoiceSession's turn steps and rules read, as the VoiceCall interface."""

from __future__ import annotations

import concurrent.futures
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Sequence, Set, Tuple

from ..keys import follow_up_key
from ..runtime.question_records import QuestionRecords
from ..understanding.word_rules import (
    _FOLLOW_UP_WORDS,
    _URGENT,
    _identifiers,
    _is_context_dependent,
    _is_personal,
    _urgent,
    _words,
)
from .channel import Channel

if TYPE_CHECKING:
    from ..channels.voice_session import VoiceSession

# How many follow-ups back a turn may lean on before it is treated as unresolvable.
CHAIN_LIMIT = 6
MS_PER_SECOND = 1000.0


class SessionCall:
    """A voice call as its rules and turn steps see it (``VoiceCall``). The session's settings are read
    live (an app may change them between turns); what the call works out from what it has heard is
    done here: the earlier turns a follow-up leans on (``chain``), a turn's cache key, a turn after an
    urgent one, the IDs the caller said before, whose system prompts it is compared with, and whether
    the server vouches for what it caches (asked inside the budget). The session's ``state`` remembers how
    each turn was read; ``read_pool`` and ``submit_write`` run the question records' reads and writes."""

    def __init__(self, session: "VoiceSession", *, read_pool: concurrent.futures.Executor,
                 submit_write: Callable[..., Any]) -> None:
        self._session = session
        self._read_pool = read_pool
        self._submit_write = submit_write

    @property
    def channel(self) -> Channel:
        return self._session.channel

    @property
    def tainted(self) -> bool:
        return self._session.state.tainted

    @property
    def values(self) -> Dict[str, str]:
        return self._session.values

    @property
    def min_words(self) -> int:
        return self._session.min_words

    @property
    def short_turns(self) -> bool:
        return self._session.short_turns

    @property
    def serve_above(self) -> float:
        return self._session.serve_above

    @property
    def commitments(self) -> str:
        return self._session.commitments

    def is_personal(self, text: str) -> bool:
        return self._session.state.is_personal(text)

    def is_context_dependent(self, text: str) -> bool:
        return self._session.state.is_context_dependent(text)

    def stated(self) -> Sequence[str]:
        return tuple(self._session.state.stated)

    def facts(self) -> Sequence[str]:
        return tuple(self._session.state.facts)

    def mark_private(self, text: str) -> None:
        self._session.state.mark_private(text)

    def private_words(self) -> Set[str]:
        return set(self._session.state.private_raw)

    def mark_tainted(self) -> None:
        self._session.state.tainted = True

    def engine_vouches(self) -> bool:
        """Whether the server judges what it caches, asked inside this call's budget: a slow answer
        is a no for this turn, and is there for the next."""
        agent, budget_ms = self._session.agent, self._session.latency_budget_ms
        if budget_ms is None:
            return agent.decides()
        try:
            return self._read_pool.submit(agent.decides).result(timeout=budget_ms / MS_PER_SECOND)
        except concurrent.futures.TimeoutError:
            return False

    def chain(self) -> Optional[List[str]]:
        """The earlier caller turns a follow-up leans on, oldest first: back to the latest one that
        stands on its own. None when there is no such turn."""
        chain: List[str] = []
        for turn in reversed(self._session.transcript):
            if turn["role"] != "user":
                continue
            chain.insert(0, turn["content"])
            if not _is_context_dependent((turn["content"] or "").strip()):
                return chain
            if len(chain) >= CHAIN_LIMIT:
                return None
        return None

    def after_urgent(self, text: str) -> bool:
        """A short turn after a private emergency or medical turn ("is he going to be okay?", "how do
        i make her vomit?"): about that turn, so answered with the call."""
        if len(_words(text)) > _FOLLOW_UP_WORDS:
            return False
        earlier = [turn["content"] or "" for turn in self._session.transcript if turn["role"] == "user"]
        for said in reversed(earlier[-CHAIN_LIMIT:]):
            words = _words(said)
            if (any(w in _URGENT for w in words) or _urgent(words)) and _is_personal(said):
                return True
            if len(words) > _FOLLOW_UP_WORDS:
                return False
        return False

    def context_key(self, said: str, text: str) -> Optional[str]:
        """The cache key of a turn: its words, or its chain for a follow-up; None without one."""
        if not self._session.state.is_context_dependent(text):
            return follow_up_key(said)
        chain = self.chain()
        return None if chain is None else follow_up_key(said, chain)

    def answers_another_question(self, asked: str, answer: str, spent_ms: float = 0.0) -> bool:
        """Whether every question this answer was saved for asks about something else, read within
        what the lookup left of the budget. Unknown means no: as before."""
        budget_ms = self._session.latency_budget_ms
        left = None if budget_ms is None else budget_ms - spent_ms
        return self.question_records().answers_another_question(asked, answer, left)

    def said_identifiers(self) -> Set[str]:
        """The ID-like values this caller said earlier in the call: its earlier turns in the
        transcript and the turns the session only heard (private turns, loaded history). Called once
        the turn being recorded is in the transcript, so that turn is left out: it passed the
        personal rules, so its numbers are not private."""
        said = [turn["content"] for turn in self._session.transcript if turn["role"] == "user"][:-1]
        return _identifiers(said + sorted(self._session.state.heard))

    def agent_key(self) -> Tuple:
        """Which agent's system prompts this call's is compared with."""
        agent = self._session.agent
        tenant = getattr(agent, "tenant", None) or getattr(getattr(agent, "_client", None), "tenant", None)
        return (tenant, getattr(agent, "agent_id", None))

    def question_records(self) -> QuestionRecords:
        """Which questions each shared answer was saved for, through the session's agent of now."""
        return QuestionRecords(self._session.agent, read_pool=self._read_pool, submit_write=self._submit_write)
