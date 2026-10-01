"""Crowkis in front of a voice agent's model and text-to-speech.

``VoiceSession`` is the voice pipeline: lookups under a hard latency budget,
cached audio per voice, fillers, barge-in. Every cache decision (what to look up,
what the model reads, what may be saved) comes from ``crowkis.conversation``,
the same policy a chat backend uses; the word rules live in ``crowkis.rules``.
"""

from __future__ import annotations

import concurrent.futures
import time
from typing import Callable, Dict, List, Optional

from .agent import Agent
from .conversation import (
    FILLER, KEPT, LOOKUP, NON_ANSWER, PRIVATE, Conversation, TurnPlan,
)
# Re-exported: tests and harnesses read these from crowkis.voice.
from .rules import _abstract, _fill, _is_context_dependent, _is_non_answer, _is_personal  # noqa: F401

_LOOKUPS = concurrent.futures.ThreadPoolExecutor(max_workers=32, thread_name_prefix="crowkis-voice")


class TurnDecision:

    def __init__(
        self,
        action: str,
        *,
        text: Optional[str] = None,
        audio: Optional[bytes] = None,
        confidence: float = 0.0,
        reason: str = "",
    ) -> None:
        self.action = action
        self.text = text
        self.audio = audio
        self.confidence = confidence
        self.reason = reason
        # For a model turn: what the model must read, and whether its answer is shared.
        # None means "the whole call", and then the answer is never shared.
        self.messages: Optional[List[Dict[str, str]]] = None
        self.cacheable = False

    @property
    def served_from_cache(self) -> bool:
        return self.action == "serve"

    @property
    def served_from_filler(self) -> bool:
        return self.action == "filler"

    @property
    def needs_model(self) -> bool:
        return self.action == "infer"

    def __repr__(self) -> str:
        return (
            f"TurnDecision({self.action!r}, confidence={self.confidence:.4f}, "
            f"reason={self.reason!r})"
        )


class VoiceSession:

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
        max_turns: Optional[int] = None,
    ) -> None:
        if not 0.0 <= serve_above <= 1.0:
            raise ValueError(f"serve_above must be in 0..1, got {serve_above}")
        if latency_budget_ms is not None and latency_budget_ms <= 0:
            raise ValueError(
                f"latency_budget_ms must be positive, got {latency_budget_ms}"
            )
        voice = (voice or "").strip()
        if not voice:
            raise ValueError(
                "VoiceSession requires a voice id. Cached audio is only reusable for "
                "the voice that produced it, and switching voices mid-call is audible"
            )
        self.agent = agent
        self.voice = voice
        self.serve_above = serve_above
        self.synthesise = synthesise
        self.ttl = ttl
        self.latency_budget_ms = latency_budget_ms
        self.conversation = Conversation(min_words=min_words, values=values, fillers=fillers,
                                         max_turns=max_turns)
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
        self.not_shareable = 0
        self.non_answers = 0
        self._plan: Optional[TurnPlan] = None  # the model turn decide() last handed out

    # --- the conversation's state, as before ------------------------------------------------

    @property
    def transcript(self) -> List[Dict[str, str]]:
        return self.conversation.transcript

    @property
    def values(self) -> Dict[str, str]:
        return self.conversation.values

    @property
    def min_words(self) -> int:
        return self.conversation.min_words

    def set_values(self, **values: object) -> None:
        self.conversation.set_values(**values)

    def register_filler(self, trigger: str, response: str) -> None:
        self.conversation.register_filler(trigger, response)

    def register_fillers(self, pairs: Dict[str, str]) -> None:
        self.conversation.register_fillers(pairs)

    # --- one turn -------------------------------------------------------------------------

    def decide(self, caller_said: str) -> TurnDecision:
        plan = self.conversation.plan(caller_said)
        decision = self._decide(plan)
        self._plan = plan if decision.needs_model else None
        if decision.needs_model:
            decision.messages, decision.cacheable = plan.messages, plan.shareable
        return decision

    def _decide(self, plan: TurnPlan) -> TurnDecision:
        if plan.reason == "empty":
            self.refused_short += 1
            return TurnDecision("infer", reason="empty transcript")
        if plan.action == FILLER:
            self.filled += 1
            return TurnDecision(
                "filler",
                text=plan.filler,
                audio=self._voiced(plan.filler),
                confidence=1.0,
                reason="registered filler, answered without a lookup or a model",
            )
        if plan.reason == "short":
            self.refused_short += 1
            return TurnDecision("infer", reason="transcript too short to match safely")
        if plan.reason == "personal_no_values":
            self.refused_private += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "the caller asked about their own records and this session has no "
                    "values to fill a shared answer shape with, so nothing can be "
                    "answered from cache without one caller's answer reaching the next"
                ),
            )
        if plan.action != LOOKUP:  # no_prior_turn
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "the utterance only has meaning against an earlier turn and this "
                    "call has none, so no cache key can be built for it"
                ),
            )

        started = time.monotonic()
        lookup = lambda: self.agent.ask(  # noqa: E731
            plan.key,
            serve_above=self.serve_above,
            cheap_above=min(0.60, self.serve_above),
            template=plan.template,
            threshold=plan.threshold,
        )
        try:
            if self.latency_budget_ms is None:
                hit = lookup()
            else:
                # A hard deadline, not a check after the fact: a slow or hung
                # cache must never hold a live call past its budget.
                hit = _LOOKUPS.submit(lookup).result(timeout=self.latency_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self.over_budget += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    f"lookup passed the {self.latency_budget_ms}ms voice budget; "
                    "a late hit is worse than a fast miss"
                ),
            )
        except Exception as exc:  # noqa: BLE001 — an unreachable cache means "ask the model"
            self.lookup_errors += 1
            self.inferred += 1
            return TurnDecision("infer", reason=f"cache unavailable ({type(exc).__name__}); asking the model")
        took_ms = (time.monotonic() - started) * 1000.0
        # Cut off a slow lookup above, and refuse one that finished after the budget.
        if self.latency_budget_ms is not None and took_ms > self.latency_budget_ms:
            self.over_budget += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                confidence=hit["confidence"],
                reason=(
                    f"lookup took {took_ms:.1f}ms, past the {self.latency_budget_ms}ms "
                    "voice budget; a late hit is worse than a fast miss"
                ),
            )

        if hit["route"] != "cache":
            self.inferred += 1
            return TurnDecision(
                "infer",
                confidence=hit["confidence"],
                reason=(
                    f"confidence below the spoken-answer bar of {self.serve_above}"
                    if hit["confidence"] > 0 else "nothing similar is cached yet"
                ),
            )

        answer = self.conversation.served(plan, hit["answer"])
        if answer is None:
            self.refused_private += 1
            self.inferred += 1
            return TurnDecision(
                "infer",
                confidence=hit["confidence"],
                reason=(
                    "the shared answer shape has a slot this call has no value "
                    "for; speaking a half-filled answer is worse than a model call"
                ),
            )

        self.served += 1
        return TurnDecision(
            "serve",
            text=answer,
            audio=self._voiced(answer, cacheable=not plan.personal),
            confidence=hit["confidence"],
            reason="confident cache hit",
        )

    def cancel(self) -> bool:
        if not self.conversation.cancel():
            return False
        self.barge_ins += 1
        return True

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
        text to speak, from the cache or from the model.
        """
        decision = self.decide(caller_said)
        if not decision.needs_model:
            return decision
        decision.text = llm(self.conversation.model_messages(self._plan, system))
        self._record_model_turn(caller_said, decision.text)
        return decision

    def record_private_turn(self, caller_said: str, model_said: str) -> None:
        """Keep a turn in this call's transcript and never cache it.

        For a model that holds the whole conversation itself (a realtime speech
        model): it cannot be given ``decision.messages``, so nothing it says is shared.
        """
        plan, self._plan = self._plan, None
        if self.conversation.keep_private(caller_said, model_said) and plan is not None and plan.shareable:
            self.not_shareable += 1

    def _record_model_turn(self, caller_said: str, model_said: str) -> str:
        """Record the model's answer to the turn decide() last handled, and cache it if allowed.

        Only an answer written from ``decision.messages`` reaches this, so it is shared
        exactly when decide() said it may be. Never raises: a refused write (security
        pipeline, rate limit, cache down) must not end a call. Returns what happened:
        saved | template | kept (not shareable) | non_answer | private | refused (write failed) |
        interrupted | not_saved (empty answer, or a follow-up with nothing before it).
        """
        plan, self._plan = self._plan, None
        if plan is None or plan.said != caller_said:
            plan = self.conversation.unplanned(caller_said)
        saving = self.conversation.settle(plan, model_said)
        if saving.outcome == NON_ANSWER:
            self.non_answers += 1
        elif saving.outcome == PRIVATE:
            self.uncacheable_personal += 1
        elif saving.outcome == KEPT:
            self.not_shareable += 1
        if not saving.write:
            return saving.outcome
        try:
            self.agent.learn(saving.key, saving.text, ttl=self.ttl, template=saving.template)
        except Exception:  # noqa: BLE001 — see docstring
            self.learn_errors += 1
            return "refused"
        return saving.outcome

    def injections(self) -> List[Dict[str, str]]:
        return list(self.conversation.transcript)

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
            "not_shareable": self.not_shareable,
            "non_answers_not_saved": self.non_answers,
            "cache_hit_pct": pct(self.served),
            "filler_hit_pct": pct(self.filled),
            "model_calls_avoided_pct": pct(self.served + self.filled),
        }

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        if self.synthesise is None:
            return None
        if not cacheable:
            return self.synthesise(answer)
        return self.agent.speak(answer, self.synthesise, voice=self.voice, ttl=self.ttl)


__all__ = ["VoiceSession", "TurnDecision"]
