from __future__ import annotations

import re
import string
import time
from typing import Callable, Dict, List, Optional

from .agent import Agent

_TRIM = string.punctuation + string.whitespace

_WORDS = re.compile(r"[^\W_]+", re.UNICODE)

_SLOT = re.compile(r"\{([^{}\s]+)\}")

_CONTEXT_BOUND_THRESHOLD = 0.995

_POSSESSIVES = frozenset({"my", "our", "mine", "ours"})

_HELD_RECORDS = frozenset(
    {
        "account", "order", "orders", "balance", "booking", "bookings",
        "reservation", "subscription", "payment", "payments", "invoice",
        "invoices", "refund", "delivery", "shipment", "ticket", "claim",
        "policy", "plan", "membership", "appointment", "prescription",
        "statement", "transaction", "transactions", "card", "loan", "mortgage",
        "benefits", "package", "parcel", "return", "returns", "profile",
        "password", "address", "phone", "email", "number", "contract",
        "renewal", "bill", "billing", "charge", "charges", "deposit",
        "withdrawal", "transfer", "case", "complaint",
    }
)

_PROCEDURAL = (
    ("how", "do", "i"),
    ("how", "do", "we"),
    ("how", "to"),
    ("how", "can", "i"),
    ("how", "can", "we"),
    ("steps", "to"),
    ("where", "do", "i"),
    ("can", "i"),
    ("can", "we"),
    ("is", "there", "a", "way"),
    ("walk", "me", "through"),
    ("help", "me"),
    ("guide",),
    ("tutorial",),
)

_OWNER_PREPOSITIONS = frozenset(
    {
        "from", "in", "on", "to", "at", "for", "with", "of", "about", "into",
        "onto", "under", "via",
    }
)

_STATE_LEADS = frozenset(
    {
        "what", "whats", "when", "where", "which", "who", "how", "is", "are",
        "has", "have", "had", "did", "do", "does", "show", "tell", "check",
        "status",
    }
)

_CONNECTIVES = frozenset({"and", "so", "but", "or", "also", "then"})

_CONNECTIVE_PAIRS = frozenset({"what about", "how about", "ok and", "okay and"})

_ELLIPSIS_LEADS = frozenset(
    {"for", "with", "about", "in", "on", "at", "to", "from", "by"}
)

_ANAPHOR_PHRASES = ("this one", "the second one", "the first one", "the other one")

_ANAPHORS = frozenset({"that", "those", "it", "them"})

_DEMONSTRATIVES = frozenset({"that", "those"})

_FUNCTION_WORDS = frozenset(
    {
        "a", "about", "am", "an", "and", "any", "are", "as", "at", "be", "been",
        "but", "by", "can", "could", "did", "do", "does", "for", "from", "how",
        "i", "if", "in", "is", "it", "many", "me", "much", "my", "no", "not",
        "of", "ok", "okay", "on", "one", "or", "our", "please", "should", "so",
        "that", "the", "their", "them", "then", "there", "these", "they",
        "this", "those", "to", "us", "was", "were", "what", "whats", "when",
        "where", "which", "who", "why", "will", "with", "would", "you", "your",
    }
)


def _normalise(text: str) -> str:
    return " ".join((text or "").strip(_TRIM).lower().split())


def _words(text: str) -> List[str]:
    return _WORDS.findall((text or "").lower())


def _contains(words: List[str], phrase: tuple) -> bool:
    span = len(phrase)
    return any(
        tuple(words[start:start + span]) == phrase
        for start in range(len(words) - span + 1)
    )


def _owned_record_at(words: List[str]) -> Optional[int]:
    for index, word in enumerate(words):
        if word not in _POSSESSIVES:
            continue
        if any(near in _HELD_RECORDS for near in words[index + 1:index + 3]):
            return index
    return None


def _is_state_interrogative(words: List[str]) -> bool:
    return words[0] in _STATE_LEADS or "status" in words


def _is_personal(text: str) -> bool:
    words = _words(text)
    index = _owned_record_at(words)
    if index is None:
        return False
    if any(_contains(words, phrase) for phrase in _PROCEDURAL):
        return False
    if index > 0 and words[index - 1] in _OWNER_PREPOSITIONS:
        return _is_state_interrogative(words)
    return True


def _has_antecedent(before: List[str]) -> bool:
    return any(word not in _FUNCTION_WORDS for word in before)


def _has_bare_anaphor(words: List[str]) -> bool:
    joined = " ".join(words)
    for phrase in _ANAPHOR_PHRASES:
        at = joined.find(phrase)
        if at >= 0 and not _has_antecedent(joined[:at].split()):
            return True
    for index, word in enumerate(words):
        if word not in _ANAPHORS:
            continue
        follows = words[index + 1] if index + 1 < len(words) else None
        if (
            word in _DEMONSTRATIVES
            and follows is not None
            and follows not in _FUNCTION_WORDS
        ):
            continue
        if not _has_antecedent(words[:index]):
            return True
    return False


def _is_context_dependent(text: str) -> bool:
    words = _words(text)
    if not words:
        return False
    if words[0] in _CONNECTIVES:
        return True
    if " ".join(words[:2]) in _CONNECTIVE_PAIRS:
        return True
    if words[0] in _ELLIPSIS_LEADS:
        return True
    return _has_bare_anaphor(words)


def _fill(shape: str, values: Dict[str, str]) -> Optional[str]:
    filled = shape
    for name in _SLOT.findall(shape):
        value = values.get(name)
        if value is None:
            return None
        filled = filled.replace("{" + name + "}", value)
    return filled


def _abstract(answer: str, values: Dict[str, str]) -> str:
    shaped = answer
    for name, value in sorted(values.items(), key=lambda pair: -len(pair[1] or "")):
        if value:
            shaped = shaped.replace(value, "{" + name + "}")
    return shaped


def _flatten(text: str) -> str:
    return "".join(_words(text))


def _leaks(shaped: str, values: Dict[str, str]) -> bool:
    flat = _flatten(shaped)
    return any(value and _flatten(value) in flat for value in values.values())


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
        self.min_words = min_words
        self.synthesise = synthesise
        self.ttl = ttl
        self.latency_budget_ms = latency_budget_ms
        self.values: Dict[str, str] = {}
        self.transcript: List[Dict[str, str]] = []
        self.served = 0
        self.inferred = 0
        self.filled = 0
        self.refused_short = 0
        self.refused_private = 0
        self.uncacheable_personal = 0
        self.over_budget = 0
        self.barge_ins = 0
        self._fillers: Dict[str, str] = {}
        self._open = False
        self._cancelled = False
        self._turn_mark = 0
        if values:
            self.set_values(**values)
        if fillers:
            self.register_fillers(fillers)

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
        self._turn_mark = len(self.transcript)
        self._open = True
        self._cancelled = False

        text = (caller_said or "").strip()
        if not text:
            self.refused_short += 1
            return TurnDecision("infer", reason="empty transcript")

        filler = self._fillers.get(_normalise(text))
        if filler is not None:
            self.filled += 1
            return TurnDecision(
                "filler",
                text=filler,
                audio=self._voiced(filler),
                confidence=1.0,
                reason="registered filler, answered without a lookup or a model",
            )

        if len(text.split()) < self.min_words:
            self.refused_short += 1
            return TurnDecision("infer", reason="transcript too short to match safely")

        personal = _is_personal(text)
        if personal and not self.values:
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

        context_bound = _is_context_dependent(text)
        keyed = self._context_key(caller_said, text)
        if keyed is None:
            self.inferred += 1
            return TurnDecision(
                "infer",
                reason=(
                    "the utterance only has meaning against an earlier turn and this "
                    "call has none, so no cache key can be built for it"
                ),
            )

        started = time.monotonic()
        hit = self.agent.ask(
            keyed,
            serve_above=self.serve_above,
            cheap_above=min(0.60, self.serve_above),
            template=personal,
            threshold=_CONTEXT_BOUND_THRESHOLD if context_bound else None,
        )
        took_ms = (time.monotonic() - started) * 1000.0

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
                reason=f"confidence below the spoken-answer bar of {self.serve_above}",
            )

        answer = hit["answer"]
        if personal:
            answer = _fill(answer, self.values)
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
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": answer})
        return TurnDecision(
            "serve",
            text=answer,
            audio=self._voiced(answer, cacheable=not personal),
            confidence=hit["confidence"],
            reason="confident cache hit",
        )

    def cancel(self) -> bool:
        if not self._open:
            return False
        self._open = False
        self._cancelled = True
        self.barge_ins += 1
        del self.transcript[self._turn_mark:]
        return True

    def record_model_turn(self, caller_said: str, model_said: str) -> None:
        if self._cancelled:
            return
        self._open = False
        text = (caller_said or "").strip()
        keyed = self._context_key(caller_said, text)
        self.transcript.append({"role": "user", "content": caller_said})
        self.transcript.append({"role": "assistant", "content": model_said})
        if not (model_said and model_said.strip()) or keyed is None:
            return
        if _is_personal(text):
            self._learn_personal(keyed, model_said)
            return
        self.agent.learn(keyed, model_said, ttl=self.ttl)

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
            "cache_hit_pct": pct(self.served),
            "filler_hit_pct": pct(self.filled),
            "model_calls_avoided_pct": pct(self.served + self.filled),
        }

    def _prior_user(self) -> Optional[str]:
        for turn in reversed(self.transcript):
            if turn["role"] == "user":
                return turn["content"]
        return None

    def _context_key(self, caller_said: str, text: str) -> Optional[str]:
        if not _is_context_dependent(text):
            return caller_said
        prior = self._prior_user()
        if prior is None:
            return None
        return f"{prior} || {caller_said}"

    def _learn_personal(self, keyed: str, model_said: str) -> None:
        shaped = _abstract(model_said, self.values)
        if (
            self.values
            and _SLOT.search(shaped)
            and not _leaks(shaped, self.values)
        ):
            self.agent.learn(keyed, shaped, ttl=self.ttl, template=True)
            return
        self.uncacheable_personal += 1

    def _voiced(self, answer: str, *, cacheable: bool = True) -> Optional[bytes]:
        if self.synthesise is None:
            return None
        if not cacheable:
            return self.synthesise(answer)
        return self.agent.speak(answer, self.synthesise, voice=self.voice, ttl=self.ttl)


__all__ = ["VoiceSession", "TurnDecision"]
