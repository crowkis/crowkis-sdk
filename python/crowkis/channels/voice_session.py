from __future__ import annotations

import collections
import concurrent.futures
import inspect
import logging
import re
import string
import threading
import time
from typing import Any, Callable, Dict, Iterable, Iterator, List, Optional, Tuple, Union

from ..client.agent import Agent, _voice_addon_missing
from ..client.commands import CrowkisClient
from ..client.connection import CrowkisError
from ..rules import RuleSet
from ..runtime import BoundedWriter, CacheLookup, TurnPairing, WriteWorkers
from ..runtime.stats import Counter, CounterField, Stats
from ..turns.voice.call import SessionCall
from ..turns.results import TurnDecision
from ..turns.values import Outcome
from ..turns.values import RecordedOutcome as _Outcome  # noqa: F401 - re-exported (old name)
from ..turns.results import VoiceAnswered
from ..turns.core import TurnCore
from ..turns.voice.turn import VoiceReader
from ..turns.voice.steps import VoiceReport
from ..turns.voice.steps import VoiceSaving
from ..understanding.slots import (
    NoRewrite,
    BudgetedUnderstanding,
    TextOnlyClassifier,
    Classifier,
    Rewriter,
    WordRuleClassifier,
)
from ..turns.values import VOICE, Channel
from ..keys import KnowledgeSegment
from ..state.call_state import CallState
from ..runtime.question_records import QUESTION_TTL, QUESTIONS_KEPT, QuestionRecords, question_key, tenant_of
from ..understanding.word_rules.call_context import _sets_context
from ..understanding.word_rules.personal import _carries_call_context
from ..understanding.word_rules.text import _COMMITMENTS, _normalise

# The server takes at most this per count in one report.
_REPORT_MAX = 1_000_000

_LOG = logging.getLogger("crowkis")


# Which questions each shared answer was saved for: runtime/question_records.py (names kept here).
_QUESTIONS_KEPT = QUESTIONS_KEPT
_QUESTION_TTL = QUESTION_TTL
_question_key = question_key
_tenant_of = tenant_of


# --- Turns whose answer must never be shared ------------------------------------------
# Kept word for word with the Node SDK (voice.js). Each group fails closed: a
# match means "answer fresh, never cache".


# A system prompt can carry one caller's details ("The caller is Asha Rao, account 99812").
# An answer that repeats them must never be shared. Two ways to find them:
#
# 1. Across calls (the reliable one). A bot's own instructions are the same on every call;
#    what changes from call to call is about the caller. Once an agent has been seen with
#    two different system prompts, every word and number of this call's prompt that is not
#    in all of them is a caller detail: any name, in any case or script, any record or
#    JSON value, any number. The business's fixed text never blocks sharing.
# 2. Before that (the first call an agent makes in this process, or a prompt that has
#    never changed): the sentences of the prompt that are about a person. The capitalised
#    words (names), email words and numbers in them are caller details.


# How many already-checked caller turns a session remembers for _heard() (past it, a turn is checked again).
_HEARD_MAX = 2048

_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="crowkis-voice")
# A plugged-in classifier and rewriter run here, inside the understanding budget.
_UNDERSTANDING = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="crowkis-voice-understand")
# A write a turn stopped waiting for (past twice the latency budget) finishes on these
# workers. Daemon threads, so a write to a hung server never holds up the program's exit
# (a cache write lost at exit costs a later hit). At most _WRITES_MAX wait at once: past
# it (a hung server) a new answer is not written at all.
_WRITE_WORKERS = 16
_WRITES_MAX = 256
# The process-wide write workers every session shares; their pending set and waiter keep the
# old names, which tests read.
_WRITES = WriteWorkers(_WRITE_WORKERS)
_PENDING_WRITES = _WRITES.pending
_submit_write = _WRITES.submit
_wait_for_writes = _WRITES.wait


# What _record_model_turn did with an answer; the two that put it in the shared cache.
_STORED = frozenset({Outcome.SAVED, Outcome.TEMPLATE})


class VoiceResponse:
    """What VoiceSession.respond() returns: iterate it for the text to speak, piece by
    piece as the model writes it.

    ``decision`` is ready at once, before the first piece: ``decision.served_from_cache``
    and ``decision.audio`` say whether a cached answer (and its audio) can be played
    instead of running the TTS. A response is read once.
    """

    def __init__(self, session: "VoiceSession", decision: "TurnDecision", caller_said: str,
                 llm, system, private) -> None:
        self.decision = decision
        self._session = session
        self._caller_said = caller_said
        self._llm = llm
        self._system = system
        self._private = private
        self._pieces: Optional[Iterator[str]] = None

    def __iter__(self) -> Iterator[str]:
        if self._pieces is not None:
            raise RuntimeError("a VoiceResponse is read once")
        self._pieces = self._run()
        return self._pieces

    def close(self) -> None:
        """Stop early: the model's stream is closed and nothing is stored."""
        if self._pieces is None:
            self._pieces = iter(())
        else:
            self._pieces.close()  # type: ignore[union-attr]

    def _stopped(self) -> bool:
        """The caller talked over this turn, a newer turn was decided, or the app
        recorded the turn itself: speak no more of this answer."""
        return self.decision._recorded or self._session._pairing.moved_on(self.decision.turn)

    def _run(self) -> Iterator[str]:
        session, decision = self._session, self.decision
        if not decision.needs_model:
            if decision.text:
                yield decision.text
            return
        if self._stopped():  # talked over before a word was read: never call the model
            session._interrupted(decision, "")
            return
        # As answer() does, so a subclass whose decide() returns its own decision works.
        decision._said = self._caller_said
        messages = decision.messages
        if messages is None:
            messages = session.injections() + [{"role": "user", "content": self._caller_said}]
        if self._system:
            messages = [{"role": "system", "content": self._system}] + messages
        source = self._llm(messages)
        if inspect.isawaitable(source) or hasattr(source, "__aiter__"):
            if inspect.iscoroutine(source):
                source.close()  # never awaited: closed so it raises no warning
            raise TypeError(
                "respond() got an async model: VoiceSession.respond() reads a sync iterable "
                "of text; for an async model use crowkis.async_voice_session() or AsyncVoiceSession"
            )
        if isinstance(source, (bytes, bytearray)):
            raise TypeError("respond() expects the model to give text (str), got bytes; decode it first")
        if isinstance(source, str):
            source = [source]
        try:
            upstream = iter(source)
        except TypeError:
            raise TypeError(
                f"respond() expects the model to give text: a str, or an iterable of str "
                f"pieces; got {type(source).__name__}"
            ) from None
        parts: List[str] = []
        ended = moved_on = False
        try:
            for piece in upstream:
                if piece is None:
                    continue
                if not isinstance(piece, str):
                    raise TypeError(
                        f"respond() expects the model to give text pieces (str), got "
                        f"{type(piece).__name__}; map each chunk to its text first"
                    )
                if self._stopped():
                    moved_on = True
                    break
                parts.append(piece)
                if piece:
                    yield piece
            else:
                ended = True
        finally:
            closer = getattr(upstream, "close", None)
            if closer is not None:
                try:
                    closer()
                except Exception:  # noqa: BLE001 — the stream is over either way
                    pass
            if moved_on:
                session._interrupted(decision, "".join(parts))
            elif ended:
                # A full answer is recorded under answer()'s rules.
                with session._turn_lock:
                    recorded, decision._recorded = decision._recorded, True
                if not recorded:
                    session._record_decision(decision, "".join(parts), private=self._private, system=self._system)


class VoiceSession:

    served = CounterField(Counter.SERVED)
    filled = CounterField(Counter.FILLED)
    inferred = CounterField(Counter.INFERRED)
    refused_short = CounterField(Counter.REFUSED_SHORT)
    refused_private = CounterField(Counter.REFUSED_PRIVATE)
    uncacheable_personal = CounterField(Counter.UNCACHEABLE_PERSONAL)
    over_budget = CounterField(Counter.OVER_BUDGET)
    barge_ins = CounterField(Counter.BARGE_INS)
    lookup_errors = CounterField(Counter.LOOKUP_ERRORS)
    learn_errors = CounterField(Counter.LEARN_ERRORS)
    slow_writes = CounterField(Counter.SLOW_WRITES)
    different_question = CounterField(Counter.DIFFERENT_QUESTION)
    not_shareable = CounterField(Counter.NOT_SHAREABLE)
    held_commitments = CounterField(Counter.HELD_COMMITMENTS)
    unspeakable = CounterField(Counter.UNSPEAKABLE)
    empty_answers = CounterField(Counter.EMPTY_ANSWERS)
    audio_unavailable = CounterField(Counter.AUDIO_UNAVAILABLE)
    understand_timeouts = CounterField(Counter.UNDERSTAND_TIMEOUTS)
    understand_errors = CounterField(Counter.UNDERSTAND_ERRORS)

    def __init__(
        self,
        agent: Agent,
        *,
        voice: str,
        serve_above: float = 0.92,
        min_words: int = 3,
        synthesise: Optional[Callable[[str], bytes]] = None,
        ttl: Optional[int] = None,
        latency_budget_ms: Optional[float] = None,
        fillers: Optional[Dict[str, str]] = None,
        values: Optional[Dict[str, str]] = None,
        commitments: str = "exact",
        short_turns: bool = False,
        share_templates: bool = False,
        language: str = "und",
        speed: str = "1",
        audio_format: str = "default",
        bytes_per_second: Optional[int] = None,
        classifier: Optional[Classifier] = None,
        rewriter: Optional[Rewriter] = None,
        understand_budget_ms: Optional[float] = None,
        channel: Union[Channel, str] = VOICE,
        knowledge_version: str = "1",
    ) -> None:
        if not 0.0 <= serve_above <= 1.0:
            raise ValueError(f"serve_above must be in 0..1, got {serve_above}")
        if commitments not in _COMMITMENTS:
            raise ValueError(
                f"commitments must be one of {sorted(_COMMITMENTS)}, got {commitments!r}"
            )
        if latency_budget_ms is not None and latency_budget_ms <= 0:
            raise ValueError(
                f"latency_budget_ms must be positive, got {latency_budget_ms}"
            )
        if understand_budget_ms is not None and not understand_budget_ms > 0:
            raise ValueError(f"understand_budget_ms must be positive, got {understand_budget_ms}")
        voice = (voice or "").strip()
        if not voice:
            raise ValueError(
                "VoiceSession requires a voice id. Cached audio is only reusable for "
                "the voice that produced it, and switching voices mid-call is audible"
            )
        self.agent = agent
        self.voice = voice
        # What changes the sound besides the voice: a clip is reused only when
        # all of these match (Voice add-on).
        self.language = language
        self.speed = speed
        self.audio_format = audio_format
        self.bytes_per_second = bytes_per_second
        # What the channel can do, as the rules read it (a voice call unless a factory says otherwise).
        self.channel = Channel.of(channel)
        # One pool per tenant: every channel, with or without an understander, lives in kb=<version>.
        self._segment = KnowledgeSegment(knowledge_version).segment
        self._reported: Dict[str, int] = {}
        self.serve_above = serve_above
        self.min_words = min_words
        self.synthesise = synthesise
        self.ttl = ttl
        self.latency_budget_ms = latency_budget_ms
        self.commitments = commitments
        self.short_turns = short_turns
        # Off by default: a template is cut from an answer the model wrote with the whole
        # call in view, so what is left outside its slots can hold what the caller said.
        self.share_templates = share_templates
        self.values: Dict[str, str] = {}
        self.transcript: List[Dict[str, str]] = []
        # The counters stats() reports; each public counter attribute reads and writes one of them.
        self._stats = Stats()
        self.served = 0
        self.inferred = 0
        self.filled = 0
        self.refused_short = 0
        self.refused_private = 0
        self.uncacheable_personal = 0
        self.over_budget = 0
        self.barge_ins = 0
        self.lookup_errors = 0
        self.learn_errors = 0
        # Writes the turn stopped waiting for at the latency budget (they finish in the background).
        self.slow_writes = 0
        # Hits refused because the stored answer was saved for a different question.
        self.different_question = 0
        self.not_shareable = 0
        self.held_commitments = 0
        self.unspeakable = 0
        self.empty_answers = 0
        self.audio_unavailable = 0
        self._fillers: Dict[str, str] = {}
        # Which turn an answer belongs to: numbering, barge-in and whether its answer may be shared.
        self._pairing = TurnPairing(session=self)
        # What this call has heard and how each turn was read; tainted: once the caller tells the call
        # something a later answer may depend on, nothing in it is looked up or shared. Only a session
        # with an understander collects stated turns, facts and private words.
        self.state = CallState(remembers_told=classifier is not None)
        # Turn number and flag change together: two decide() calls never share a turn.
        self._turn_lock = self._pairing.lock
        # The checks of the three SDK stages, read through this call's view of the session.
        self._rules = RuleSet.voice(self._fillers) if classifier is None else RuleSet.understood(self._fillers)
        # How a turn is understood: the word rules, and no rewrite, until an understander is plugged in.
        self._classifier = TextOnlyClassifier.fit(classifier) if classifier is not None else WordRuleClassifier()
        self._rewriter = rewriter if rewriter is not None else NoRewrite()
        # A plugged-in model runs inside its error boundary and budget (None: no deadline); late or
        # failed, the word rules read the turn (counted).
        self._understanding_budgeted = classifier is not None or rewriter is not None
        if self._understanding_budgeted:
            understanding = BudgetedUnderstanding(self._classifier, self._rewriter, budget_ms=understand_budget_ms,
                                                  pool=_UNDERSTANDING, count=self._stats.add)
            self._classifier = self._rewriter = understanding
        self._call = SessionCall(self, read_pool=_LOOKUPS, submit_write=_submit_write)
        # Writes wait at most twice the budget; the cap is read when a write starts.
        self._writer = BoundedWriter(_WRITES, lambda: _WRITES_MAX, self._stats.add, _LOG)
        # Lookups run on the shared pool, inside the budget the call has when it looks up.
        self._cache_lookup = CacheLookup(_LOOKUPS)
        # The turn's fixed steps; this session keeps the call's transcript, fillers, audio and counters.
        self._core = self._build_core(self._rules)
        if values:
            self.set_values(**values)
        if fillers:
            self.register_fillers(fillers)

    @property
    def _tainted(self) -> bool:
        return self.state.tainted

    @_tainted.setter
    def _tainted(self, value: bool) -> None:
        self.state.tainted = value

    @property
    def _heard_texts(self) -> set:
        return self.state.heard

    def _build_core(self, rules: RuleSet) -> TurnCore:
        """The one TurnCore with a voice call's parts (this session is their composition root):
        ``rules`` are the question, hit and save checks. The session is the core's live settings."""
        self._report = report = VoiceReport(self, self._stats, voiced=self._voiced, pairing=self._pairing,
                                            call=self._call, state=self.state)
        reader = VoiceReader(classifier=self._classifier, rewriter=self._rewriter,
                             state=self.state, call=self._call, segment=self._segment)
        self._saving = VoiceSaving(self, rules=rules, call=self._call, state=self.state,
                                   report=report, writer=self._writer, stats=self._stats, segment=self._segment)
        return TurnCore(self, pairing=self._pairing, answers=report, reader=reader,
                        question_check=rules, cache_lookup=self._cache_lookup, hit_check=rules, report=report,
                        saving=self._saving)

    def set_values(self, **values: object) -> None:
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

    def decide(self, caller_said: str) -> TurnDecision:
        return self._core.decide(caller_said)

    def cancel(self) -> bool:
        # Under the turn lock, like decide() and recording: a save finishing on another
        # thread never adds to the transcript while it is being trimmed.
        return self._pairing.cancel(self._talked_over)

    def _talked_over(self, mark: int) -> None:
        """The open turn was cancelled: count the barge-in, drop the turn from the transcript."""
        self.barge_ins += 1
        del self.transcript[mark:]

    def answer(
        self,
        caller_said: str,
        llm: Callable[[List[Dict[str, str]]], str],
        *,
        system: Optional[str] = None,
    ) -> TurnDecision:
        """Run one caller turn end to end: cache, or the model, then remember the answer.

        ``llm`` is called with exactly the messages Crowkis chose for this turn: the
        question alone (or with the question before it) when the answer may be shared,
        the whole call when it may not. ``system`` is the app's own instructions, the
        same for every caller, and is put first. The returned decision carries the
        text to speak, from the cache or from the model, and ``stored`` /
        ``not_stored`` say whether the model's answer was cached and why not. A
        model that says nothing sets ``empty``: retry, or speak a fallback.
        """
        decision = self.decide(caller_said)
        if not decision.needs_model:
            return decision
        messages = decision.messages
        if messages is None:
            messages = self.injections() + [{"role": "user", "content": caller_said}]
        if system:
            messages = [{"role": "system", "content": system}] + messages
        # Straight to the recording step: answer() made this decision itself, so a
        # subclass whose decide() returns its own decision object keeps working.
        decision._said = caller_said
        return self._record_decision(decision, llm(messages), private=False, system=system)

    def record(self, decision: TurnDecision, answer: Optional[str], *, private: bool = False,
               system: Optional[str] = None) -> TurnDecision:
        """Save the answer to a turn you sent to your own model: decide(), then call
        the model with ``decision.messages``, then record(decision, its answer).

        The same rules as answer() decide what happens to it: shared with other
        callers only when decide() said it may be (``decision.cacheable``), kept to
        this call otherwise, and dropped when the caller talked over it (cancel()) or
        a newer turn was decided since. ``private=True`` keeps a shareable answer to
        this call, e.g. one built from a tool's result. ``system`` is the system prompt
        the model read, if any: an answer that repeats a detail it gives about this
        caller (a name, an account number) is kept to this call. Never raises for the
        server: a refused write is reported, not thrown.

        Returns ``decision`` with ``text`` set to the answer and ``stored`` /
        ``not_stored`` / ``empty`` filled in, as answer() does. Raises ValueError for a
        decision this session did not make, one that did not need the model (served
        from the cache or a filler), or one already recorded.
        """
        if not isinstance(decision, TurnDecision):
            raise ValueError(f"record() takes the TurnDecision decide() returned, got {type(decision).__name__}")
        with self._turn_lock:  # two threads recording one decision: only one gets through
            if decision._recorded:
                raise ValueError("record() got a decision that was already recorded")
            owner = decision._session() if decision._session is not None else None
            if owner is not self:
                raise ValueError(
                    "record() takes a decision from this session's decide(); one from another "
                    "session (another call) or made by hand is refused"
                    if decision._session is None else
                    "record() got a decision from another session: each call's answers are "
                    "recorded in the session that decided them"
                )
            if not decision.needs_model:
                where = "a filler" if decision.served_from_filler else "the cache"
                raise ValueError(
                    f"record() is for a turn that needed the model; this one was answered "
                    f"by {where} ({decision.action!r})"
                )
            decision._recorded = True
        return self._record_decision(decision, answer, private=private, system=system)

    def _record_decision(self, decision: TurnDecision, answer: Optional[str], *, private: bool,
                         system: Optional[str] = None) -> TurnDecision:
        """record() and answer(): store the answer and fill in the decision."""
        decision._recorded = True
        said, decision._said = decision._said, None
        decision.text = answer
        outcome = self._record_model_turn(said, answer, turn=decision.turn, private=private, instructions=system)
        decision.stored = outcome in _STORED
        decision.save_rule = None if decision.stored else outcome.rule
        why = "" if decision.stored else (outcome.why or str(outcome))
        decision.not_stored = why
        if not (decision.text or "").strip():
            decision._empty = True
            decision.reason = "the model returned an empty answer; retry or speak a fallback"
        elif why:
            decision.reason = f"{decision.reason}; not stored: {why}"
        return decision

    def respond(
        self,
        caller_said: str,
        llm: Callable[[List[Dict[str, str]]], Union[str, Iterable[Optional[str]]]],
        *,
        system: Optional[str] = None,
        private: bool = False,
    ) -> VoiceResponse:
        """answer(), streamed: decide now, then give the text to speak piece by piece.

        ``llm(messages)`` returns the model's text pieces as it writes them (any
        iterable of str; None pieces are skipped) or the whole answer as one str. It is
        called with the same messages answer() would use, only when the turn needs
        the model, and only once the response is read.

        A turn the cache or a filler answers yields that text once (``decision.audio``
        has its audio when the session caches audio). A model turn yields the model's
        pieces and, when its stream ends, records the full answer under answer()'s rules
        (``private`` as in record()). If the caller talks over it (cancel()) or a newer
        turn is decided, the stream stops at the next piece, the model's stream is
        closed and nothing is stored. A model error is raised and stores nothing, as
        does stopping early (``close()``, or leaving the loop); the decision can then
        still be recorded with record().
        """
        decision = self.decide(caller_said)
        return VoiceResponse(self, decision, caller_said, llm, system, private)

    def _interrupted(self, decision: TurnDecision, spoken: str) -> None:
        """A streamed turn the caller talked over: report it, store and keep nothing.
        Not an empty answer, so an app never retries over the caller's new words."""
        with self._turn_lock:
            if decision._recorded:
                return
            decision._recorded = True
        decision._said = None
        decision.text = spoken
        decision.stored = False
        decision.save_rule = "Interrupted"
        self._stats.count_rule("Interrupted")
        decision.not_stored = "the caller moved on before this answer was complete"
        decision.reason = f"{decision.reason}; not stored: {decision.not_stored}"

    def record_private_turn(self, caller_said: str, model_said: str) -> None:
        """Keep a turn in this call's transcript and never cache it.

        For a model that holds the whole conversation itself (a realtime speech
        model): it cannot be given ``decision.messages``, so nothing it says is shared.
        """
        self._heard(caller_said)
        if self._pairing.cancelled:
            return
        self._pairing.is_open = False
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": model_said})
        with self._turn_lock:
            if self._pairing.drop_shareable():
                self.not_shareable += 1

    def _heard(self, caller_said: Optional[str]) -> None:
        """A caller turn this session never decided (a private turn, history the app gave
        the model): one that tells the call something a later answer may depend on keeps
        the rest of the call off the shared cache, as decide() does for its own turns."""
        text = caller_said.strip() if isinstance(caller_said, str) else ""
        if self._tainted or not text or text in self._heard_texts:
            return
        if len(self._heard_texts) < _HEARD_MAX:
            self._heard_texts.add(text)
        if _sets_context(text):
            self._tainted = True

    def _record_model_turn(
        self, caller_said: str, model_said: str, *, turn: Optional[int] = None, private: bool = False,
        instructions: Optional[str] = None,
    ) -> str:
        """Record the model's answer to the turn decide() last handled, and cache it if allowed.

        Only an answer written from ``decision.messages`` reaches this, so it is shared
        exactly when decide() said it may be. ``turn`` is the decision's turn: an answer
        to a turn the caller talked over, or to one before the latest, is dropped, so it
        never lands on later words. ``private`` keeps it to this call whatever the turn
        was (an answer built from a tool's result). Never raises: a refused write
        (security pipeline, tenant limit, cache down) must not end a call.

        Returns what happened to the answer: ``saved`` (shared), ``template`` (shared
        as a shape, this caller's values removed), ``kept`` (the model read the whole
        call, or a tool's result, so it stays in this call), ``private`` (personal, or
        repeats this caller's details), ``non_answer``, ``not_saved`` (a follow-up with
        nothing to key it to), ``refused`` (the write failed), ``slow_write`` (a session
        with a latency budget stopped waiting for the write: not confirmed) or
        ``interrupted`` (talked over, or the caller moved on before it was complete). The returned string's
        ``why`` says it in words.
        """
        return self._core.record(VoiceAnswered(caller_said, model_said, turn, private, instructions))

    def injections(self) -> List[Dict[str, str]]:
        return list(self.transcript)

    def stats(self) -> dict:
        total = self.served + self.inferred + self.filled
        def pct(n: int) -> float:
            return round(100.0 * n / total, 2) if total else 0.0

        return {
            "turns": total,
            "served_from_cache": self.served,
            "answered_by_filler": self.filled,
            "model_calls": self.inferred,
            "refused_too_short": self.refused_short,
            "refused_to_share_a_private_answer": self.refused_private,
            "uncacheable_personal": self.uncacheable_personal,
            "missed_latency_budget": self.over_budget,
            "barge_ins": self.barge_ins,
            "cache_unavailable": self.lookup_errors,
            "failed_writes": self.learn_errors,
            "slow_writes": self.slow_writes,
            "different_question": self.different_question,
            "not_shareable": self.not_shareable,
            "commitments_sent_to_model": self.held_commitments,
            "unspeakable_answers": self.unspeakable,
            "empty_answers": self.empty_answers,
            "audio_unavailable": self.audio_unavailable,
            "cache_hit_pct": pct(self.served),
            "filler_hit_pct": pct(self.filled),
            "model_calls_avoided_pct": pct(self.served + self.filled),
            # How often each rule decided a turn or kept an answer, by the rule's name.
            "rules": self._stats.rule_counts(),
            # Turns a plugged-in model was too slow for or failed on (the word rules read them).
            **({"understand_timeouts": self.understand_timeouts, "understand_errors": self.understand_errors}
               if self._understanding_budgeted else {}),
        }

    def _reportable(self) -> Dict[str, int]:
        """The counts the Voice page shows, by the server's names."""
        return {
            "turns": self.served + self.inferred + self.filled,
            "served_from_cache": self.served,
            "filler_hits": self.filled,
            "model_calls_avoided": self.served + self.filled,
            "private_turns": self.refused_private + self.uncacheable_personal,
            "barge_ins": self.barge_ins,
            "latency_misses": self.over_budget,
            "empty_answers": self.empty_answers,
        }

    def report_stats(self) -> bool:
        """Send this session's counts since its last report to the Voice page
        (the server's Voice add-on). False when the server has no Voice add-on.
        Nothing is lost: what a failed report did not send goes with the next."""
        now = self._reportable()
        sent = {
            name: min(count - self._reported.get(name, 0), _REPORT_MAX)
            for name, count in now.items()
            if count > self._reported.get(name, 0)
        }
        if not sent:
            return True
        try:
            self.agent._client.cvoicestat(sent, tenant=self.agent.tenant)
        except CrowkisError as err:
            if _voice_addon_missing(err):
                return False
            raise
        for name, count in sent.items():
            self._reported[name] = self._reported.get(name, 0) + count
        return True

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        """The audio for an answer this turn speaks, or None. Never raises: when the
        audio step fails (the cache, or the app's own synthesiser) the turn keeps its
        text and the app's TTS speaks it."""
        if self.synthesise is None:
            return None
        try:
            return self._voice(answer, cacheable)
        except Exception as err:  # noqa: BLE001 — see docstring
            self.audio_unavailable += 1
            # The type only: an app's TTS error can quote the (possibly personal) text.
            _LOG.warning("crowkis voice: no audio for this answer, the text is still served (%s)",
                         type(err).__name__)
            return None

    def _voice(self, answer: str, cacheable: bool) -> Optional[bytes]:
        # A text-only session (voice_session() with no voice) has no real voice id to
        # key a clip on: speak, but never read or store a cached clip.
        if not cacheable or getattr(self, "_text_only", False):
            return self.synthesise(answer)
        return self.agent.speak(
            answer,
            self.synthesise,
            voice=self.voice,
            ttl=self.ttl,
            language=self.language,
            speed=self.speed,
            audio_format=self.audio_format,
            bytes_per_second=self.bytes_per_second,
        )


# The voice id of a text-only session. Never used as a cache key: every audio path
# checks `_text_only` first.
_TEXT_ONLY_VOICE = "crowkis:text-only"

# A voice_session() budget left out: it comes from the channel's profile.
_FROM_CHANNEL: Any = object()


def voice_session(
    *,
    voice: Optional[str] = None,
    agent_id: str = "voice",
    client: Optional[CrowkisClient] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    auth_token: Optional[str] = None,
    token: Optional[str] = None,
    tenant: Optional[str] = None,
    timeout: Optional[float] = None,
    channel: Union[Channel, str] = VOICE,
    latency_budget_ms: Any = _FROM_CHANNEL,
    understand_budget_ms: Any = _FROM_CHANNEL,
    **options: Any,
) -> VoiceSession:
    """A ready VoiceSession in one call, with defaults for live calls.

    It builds the client and the Agent itself. Server settings not passed here come
    from the environment, then the defaults (see the README, "Connect to your server").
    The defaults differ from a bare VoiceSession because a caller is waiting:

    - ``latency_budget_ms=250``: the longest a turn waits for a cache lookup before it
      goes to the model. ``None`` turns the budget off.
    - ``timeout=1.0`` seconds per server request, with no retries. Saving the model's
      answer happens while the caller waits; a 5 s timeout tried three times would
      leave a stuck server holding the turn for about 15 s. The cost of no retries: a
      request that fails once (the first on each pooled connection after a server
      restart, or a BUSY reply) is not tried again, so that lookup goes to the model or
      that answer is not stored. Pass your own ``client`` for other settings, e.g. for
      ``warm_from_calls``, which should not use this live-call client.

    ``voice`` is the TTS voice id. Without it the session caches text only and never
    reads or stores audio, so two voices can never share a clip; passing
    ``synthesise`` then is an error. Every other VoiceSession option (``serve_above``,
    ``fillers``, ``ttl``, ...) is passed on as it is.

    ``client`` uses a client you built, as it is: its server settings and timeouts are
    yours, so passing ``host``/``port``/``auth_token``/``token``/``tenant``/``timeout`` with
    it is an error, and closing the agent leaves it open.

    ``classifier`` / ``rewriter`` plug in a model that reads the turn (``LLMClassifier``,
    ``LLMRewriter``). It gets ``understand_budget_ms`` (250) per turn; late
    or failed, the word rules read the turn. The word rules apply either way, so a model can make
    a call more private, never less. ``None`` turns the budget off.

    ``channel`` ("voice", the default, or "realtime", or a ``Channel``) is the profile the
    budgets not passed here come from (voice and realtime: 250 ms each).
    """
    channel = Channel.of(channel)
    if latency_budget_ms is _FROM_CHANNEL:
        latency_budget_ms = channel.budget_ms
    if understand_budget_ms is _FROM_CHANNEL:
        understand_budget_ms = channel.understand_budget_ms
    if timeout is not None and not timeout > 0:
        raise ValueError(f"timeout must be a positive number of seconds, got {timeout}")
    if client is not None:
        given = [name for name, value in (("host", host), ("port", port), ("auth_token", auth_token),
                                          ("token", token), ("tenant", tenant), ("timeout", timeout))
                 if value is not None]
        if given:
            raise ValueError(
                f"voice_session() got client= and {', '.join(given)}: a client passed in is "
                "used as it is, so set these on the client instead"
            )
    if voice is None and options.get("synthesise") is not None:
        raise ValueError(
            "voice_session() got synthesise= without voice=. Cached audio is keyed on the "
            "voice that spoke it: pass your TTS voice id, or leave out synthesise to cache text only"
        )
    owns_client = client is None
    if client is None:
        client = CrowkisClient(
            host, port, auth_token=auth_token, token=token, tenant=tenant,
            timeout=1.0 if timeout is None else timeout, max_retries=0,
        )
    agent = Agent(agent_id, client=client, tenant=client.tenant)
    agent._owns_client = owns_client
    session = VoiceSession(
        agent,
        voice=_TEXT_ONLY_VOICE if voice is None else voice,
        latency_budget_ms=latency_budget_ms,
        understand_budget_ms=understand_budget_ms,
        channel=channel,
        **options,
    )
    session._text_only = voice is None
    return session


def warm_from_calls(agent: Agent, calls, *, wait: float = 30.0) -> dict:
    """Fill the cache from past calls, so it is useful on the first day.

    `calls` is an iterable of calls, each a list of `(caller_said, agent_said)`
    turns in order. A follow-up is kept with the turn it depends on, and
    nothing is spoken or synthesised.

    It needs the server's decision engine, holding answers until it has judged
    them (the default), and refuses to run otherwise. A past agent turn can
    hold details the caller never said aloud (an address looked up, a
    balance), which the live rules cannot see in a transcript; the engine
    reads every answer before anyone is served it.

    Returns totals. After each call it gives the engine up to `wait` seconds
    to catch up; `stalled` is true when it stopped early because three calls
    in a row were not judged in that time.
    """
    if not (agent.decides() and agent._holds):
        raise RuntimeError(
            "warm_from_calls needs the server's decision engine, holding answers until it has "
            "judged them (CROWKIS_DECIDE_UPSTREAM set, CROWKIS_DECIDE_SERVE_UNJUDGED not set): "
            "otherwise a past answer holding one caller's details could be shared before it is checked"
        )
    totals = {"calls": 0, "turns": 0, "kept_private": 0, "failed_writes": 0, "stalled": False}
    stalls = 0
    for call in calls:
        session = VoiceSession(agent, voice="warm-start")
        earlier: List[str] = []
        for caller_said, agent_said in call:
            # The same rule as a live turn picks the candidates. A past answer
            # was written with the whole call in view, so one that repeats what
            # identified this caller is kept out here, and the engine reads the
            # rest before anyone is served them.
            keyed = session._call.context_key(caller_said, (caller_said or "").strip()) or caller_said
            session._tainted = session._tainted or _sets_context((caller_said or "").strip())
            _, cacheable = session._report.model_messages(caller_said)
            pairing = session._pairing
            pairing.offer(pairing.turn, cacheable and not _carries_call_context(agent_said, keyed, earlier))
            session._record_model_turn(caller_said, agent_said)
            earlier.append(caller_said)
            totals["turns"] += 1
        totals["calls"] += 1
        totals["kept_private"] += session.not_shareable + session.uncacheable_personal
        totals["failed_writes"] += session.learn_errors
        # Let the engine catch up before the next call: it judges a bounded
        # number of answers at a time and refuses what does not fit.
        stalls = 0 if _judged_in_time(agent, session._saving.last_stored, wait) else stalls + 1
        if stalls >= 3:
            totals["stalled"] = True
            break
    return totals


def _judged_in_time(agent: Agent, query: Optional[str], seconds: float) -> bool:
    """False when the engine was still working on `query` after `seconds`."""
    deadline = time.monotonic() + seconds
    while query is not None and time.monotonic() < deadline:
        try:
            view = agent.explain(query)
        except Exception:  # noqa: BLE001 — cannot ask, so there is nothing to wait for
            return True
        if not isinstance(view, dict) or not view.get("pending"):
            return True
        time.sleep(min(0.2, seconds))
    return query is None


__all__ = ["VoiceSession", "TurnDecision", "warm_from_calls"]
