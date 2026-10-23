"""TurnCore: one voice turn, from the caller's words to a decision, and from the model's answer to
what is shared."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Optional, Tuple

from ..runtime.cache_lookup import CacheLookup
from ..runtime.stats import Counter, Stats
from ..runtime.turn_pairing import TurnPairing
from ..understanding.call_readings import CallReadings
from ..understanding.rewrite_check import RewriteCheck
from ..understanding.slots import Classifier, Rewriter
from ..understanding.word_rules import _CONTEXT_BOUND_THRESHOLD
from .cached_answer import CachedAnswer
from .hit import Hit
from .decision import TurnDecision, _Outcome
from .model_answer import ModelAnswer
from .turn_host import TurnHost
from .voice_call import VoiceCall
from .verdict import Verdict
from .voice_turn import VoiceTurn

if TYPE_CHECKING:
    from ..rules.rule_set import RuleSet

_LOG = logging.getLogger("crowkis")


class TurnCore:
    """Template Method: the fixed steps of a voice turn. decide(): open the turn, understand it, the
    question rules, a filler, the lookup inside the budget, the hit rules, serve. record(): pair the
    answer with its turn, the save rules, a shared shape for a personal answer, the bounded write.

    The steps' parts are injected: the rules, the classifier and rewriter (with the call's readings,
    which remember what they made of each turn), the turn pairing, the
    lookup, the call as the rules see it, and the counters (``stats``); ``host`` (TurnHost) is the
    session's transcript, settings, audio and writes."""

    def __init__(self, host: TurnHost, *, rules: "RuleSet", call: VoiceCall, pairing: TurnPairing,
                 cache_lookup: CacheLookup, classifier: Classifier, rewriter: Rewriter,
                 call_readings: CallReadings, stats: Stats, rewrite_check: Optional[RewriteCheck] = None) -> None:
        self._host = host
        self._stats = stats
        self._rules = rules
        self._call = call
        self._pairing = pairing
        self._cache_lookup = cache_lookup
        self._classifier = classifier
        self._rewriter = rewriter
        self._call_readings = call_readings
        self._rewrite_check = rewrite_check if rewrite_check is not None else RewriteCheck()

    def decide(self, caller_said: str) -> TurnDecision:
        """What this turn needs: a filler, a cached answer, or the model (and which rule said so)."""
        self._pairing.start(len(self._host.transcript))

        text = (caller_said or "").strip()
        reading = self._classifier.classify(text)
        rewritten = self._rewrite_check.accept(text, reading, self._rewriter.rewrite(text, reading), self._call)
        self._call_readings.note(text, reading, rewritten)
        turn = VoiceTurn(caller_said, self._call, reading, rewritten)
        verdict = self._rules.before_filler.first_objection(turn)
        if verdict is not None:
            return self._infer(verdict)

        filler = self._rules.filler.first_objection(turn)
        if filler is not None:
            return self._filler(filler)

        verdict = self._rules.question.first_objection(turn)
        if verdict is not None:
            return self._infer(verdict)

        started = time.monotonic()
        hit, verdict = self._lookup(turn, started)
        if verdict is not None:
            return self._infer(verdict, confidence=hit["confidence"] if hit else 0.0)

        cached = CachedAnswer(turn, Hit.from_agent(hit), started)
        verdict = self._rules.hit.first_objection(cached)
        if verdict is not None:
            return self._infer(verdict, confidence=hit["confidence"])

        self._stats.add(Counter.SERVED)
        self._host.transcript.append({"role": "user", "content": caller_said})
        self._host.transcript.append({"role": "assistant", "content": cached.answer})
        decision = TurnDecision(
            "serve",
            text=cached.answer,
            audio=self._host.voiced(cached.answer, cacheable=not turn.is_personal),
            confidence=hit["confidence"],
            reason="confident cache hit",
        )
        decision._audio_shareable = not turn.is_personal
        return decision

    def _lookup(self, turn: VoiceTurn, started: float) -> Tuple[Optional[dict], Optional[Verdict]]:
        """The cache's hit for a turn, within the latency budget, and a Verdict when the cache was
        too slow or could not be reached (the model answers then; a late hit is still returned)."""
        lookup = lambda: self._host.agent.ask(  # noqa: E731
            turn.key,
            serve_above=self._host.serve_above,
            cheap_above=min(0.60, self._host.serve_above),
            template=turn.is_personal,
            threshold=_CONTEXT_BOUND_THRESHOLD if turn.is_context_dependent or turn.is_short else None,
        )
        return self._cache_lookup.find(lookup, started, self._host.latency_budget_ms)

    def _infer(self, verdict: Verdict, *, confidence: float = 0.0) -> TurnDecision:
        """The model answers this turn: ``verdict`` says which rule decided so, and why."""
        self._count_verdict(verdict)
        self._stats.count_rule(verdict.rule)
        return TurnDecision("infer", confidence=confidence, reason=verdict.reason, rule=verdict.rule)

    def _filler(self, verdict: Verdict) -> TurnDecision:
        """A registered filler answers the turn at once (its audio may be shared)."""
        self._count_verdict(verdict)
        decision = TurnDecision(verdict.route, text=verdict.answer, audio=self._host.voiced(verdict.answer),
                                confidence=1.0, reason=verdict.reason, rule=verdict.rule)
        decision._audio_shareable = True
        return decision

    def _count_verdict(self, verdict: Verdict) -> None:
        for counter in verdict.counts:
            self._stats.add(counter)

    def record(self, caller_said: str, model_said: str, *, turn: Optional[int], private: bool,
               instructions: Optional[str]) -> "_Outcome":
        """What happens to the model's answer to ``turn`` (None: the latest): dropped when the caller
        moved on, kept to the call by a save rule, or shared. Never raises: a refused write (security
        pipeline, tenant limit, cache down) must not end a call; it is the ``refused`` outcome."""
        settled = self._pairing.settle(turn)
        if settled is None:
            return _Outcome("interrupted", "the caller moved on before this answer was complete", rule="Interrupted")
        _, shareable = settled
        answer = ModelAnswer(caller_said, model_said, None, self._call, private=private, instructions=instructions,
                             cacheable=shareable and not private)
        verdict = self._rules.answer_given.first_objection(answer)
        if verdict is not None:
            return self._kept(verdict)
        answer = answer.keyed(self._call_readings.rewritten(answer.text)
                              or self._host.context_key(caller_said, answer.text))
        self._host.transcript.append({"role": "user", "content": caller_said})
        self._host.transcript.append({"role": "assistant", "content": model_said})
        verdict = self._rules.before_sharing.first_objection(answer)
        if verdict is not None:
            return self._kept(verdict)
        try:
            if answer.is_personal:
                return self._record_personal(answer)
            verdict = self._rules.sharing.first_objection(answer)
            if verdict is not None:
                return self._kept(verdict)
            slow = self._host.learn(answer.key, model_said, ttl=self._host.ttl)
            self._host.note_stored(answer.key)
            if slow is None:  # a slow server gets no extra write
                self._host.keep_question(answer.key, model_said)
            return slow or _Outcome("saved")
        except Exception as error:  # noqa: BLE001 — a refused write must not end a call
            self._stats.add(Counter.LEARN_ERRORS)
            why = f"the server refused the write: {str(error) or type(error).__name__}"
            _LOG.warning("crowkis voice answer not stored, %s", why)
            return _Outcome("refused", why, rule="WriteRefused")

    def _record_personal(self, answer: ModelAnswer) -> "_Outcome":
        """A personal answer is shared only as a shape with this call's values taken out."""
        personal = self._rules.personal
        verdict = personal.check(answer)
        if verdict is None:
            templated = self._host.learn_personal(answer.key, answer.answer)
            if isinstance(templated, _Outcome):
                return templated  # slow_write: the shape was not confirmed written
            if templated:
                return _Outcome("template")
            verdict = personal.refusal()
        return self._kept(verdict)

    def _kept(self, verdict: Verdict) -> "_Outcome":
        """A save rule kept the answer out of the shared cache."""
        self._count_verdict(verdict)
        return _Outcome(verdict.outcome, verdict.reason, rule=verdict.rule)
