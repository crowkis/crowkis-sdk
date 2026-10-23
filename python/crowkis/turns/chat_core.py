"""ChatCore: one Chat turn, from the user's words to a route, and from the agent's answer to what is
shared. Template Method beside the voice TurnCore (a single core for both channels is P5's work)."""

from __future__ import annotations

import concurrent.futures
import copy
import time
from typing import Any, Optional, Set

from ..rules.chain import RuleChain
from ..rules.question import UrgentWords
from ..runtime.cache_lookup import CacheLookup
from ..turn import TurnFrame
from ..understanding.chat_details import _masked, _names, _norm, _private_words, _told
from ..understanding.word_rules import _identifiers, _instructs, _tells_about_caller, _words
from ..verify import AGENT, PERSONAL, SHARED, TOOLS, URGENT, Verdict
from ..runtime.bounded_writer import BoundedWriter
from ..runtime.question_records import QuestionRecords
from .chat_answer import ChatAnswer
from .chat_cached_answer import ChatCachedAnswer, ChatHitCall, ChatHitTurn
from .hit import Hit
from .chat_host import ChatHost
from .chat_turn import ChatTurn
from .routes import FILLER
from .turn_result import TurnResult

_UNDERSTAND = concurrent.futures.ThreadPoolExecutor(max_workers=16, thread_name_prefix="crowkis-understand")
# Chat's counter for each way a lookup fails open.
_LOOKUP_COUNTS = {"LookupDeadline": "lookup_timeouts", "CacheUnavailable": "lookup_errors"}


class ChatCore:
    """Template Method: the fixed steps of a Chat turn. handle(): understand the turn, run the rule
    checker and the checks once a question would be shared, the urgent words, then a filler, the tools
    or the lookup inside the budget. record(): pair the answer with its turn, the save rules, the write.
    The core owns its rule chains, its lookup and its turns (numbering, the open turn, cancelled
    ones); ``host`` (ChatHost) is the session's state, counts, settings and hooks."""

    def __init__(self, host: ChatHost, *, cache_lookup: CacheLookup, shared_question_rules: RuleChain,
                 urgent_words: UrgentWords, save_rules: RuleChain, hit_rules: RuleChain,
                 question_records: QuestionRecords, writer: BoundedWriter) -> None:
        self._host = host
        self._cache_lookup = cache_lookup
        self._hit_rules = hit_rules
        self._question_records = question_records
        self._writer = writer
        self._shared_question_rules = shared_question_rules
        self._urgent_words = urgent_words
        self._save_rules = save_rules
        self._next = 1
        self._open: Optional[TurnResult] = None
        self._cancelled: Set[int] = set()

    @property
    def next_turn(self) -> int:
        """The number the next turn will get (kept with an exported thread)."""
        return self._next

    @next_turn.setter
    def next_turn(self, value: int) -> None:
        self._next = value

    def handle(self, turn: str) -> TurnResult:
        tid, self._next = self._next, self._next + 1
        text = " ".join((turn or "").split())
        if not text:
            return self._open_turn(TurnResult(tid, AGENT, reason="empty"))
        filler = self._host.fillers.get(_norm(text))
        if filler is not None:
            self._host.counts[FILLER] += 1
            self._host.state.note_agent_reply(filler)
            return TurnResult(tid, FILLER, text=filler, needs_model=False, reason="registered filler")

        if self._host.mode == "off":
            self._host.counts["sharing_off"] += 1
            result = self._open_turn(TurnResult(tid, AGENT, reason="sharing off"))
            self._host.emit({"type": "turn", "turn_id": tid, "route": AGENT, "reasons": ["mode_off"], "shared": False})
            return result
        # What the caller tells (an allergy, an age, a trip) must reach every later shared
        # question, this turn's included: noted before the check, in fixed code.
        words = _words(text)
        about_caller = _tells_about_caller(text)
        frame = self._understand(text)
        named: Set[str] = set()
        if about_caller:
            named, details = _told(text, frame)
            self._host.state.note_stated(" ".join(w for w in words if w not in named))
            self._host.state.note_details(details)
        # On every turn and before the check: a name given in this very turn ("Hi, I'm Sarah.
        # What is the refund policy?") is never in a shared question or answer.
        names = sorted(set(_names(text, frame, fact=about_caller)) | named)
        self._host.state.note_names(names)
        self._host.state.note_identifiers(_identifiers([text]))
        if frame.language and _instructs(text, words):
            self._host.state.language = frame.language  # "reply only in Hindi": kept for the rest of the chat
        verdict = self._host.checker.check(frame, text, self._host.state)
        chat_turn = ChatTurn(frame, text, self._host.state)
        if verdict.shared:
            objection = self._shared_question_rules.first_objection(chat_turn)
            if objection is not None:
                verdict = Verdict(False, AGENT, [objection.reason])
        if verdict.route != URGENT and about_caller:
            objection = self._urgent_words.check(chat_turn)
            if objection is not None:
                verdict = Verdict(False, objection.route, [objection.reason])  # never left to the model alone
        self._host.state.apply(frame, shared=verdict.shared)
        self._host.state.note_private((_private_words(text, frame) if not verdict.shared else []) + names)
        self._host.counts[verdict.route] += 1

        if verdict.route == URGENT and self._host.on_urgent is not None:
            try:
                self._host.on_urgent(text, frame)
            except Exception:  # noqa: BLE001 - the hook must not take the call down
                pass
        if verdict.route == URGENT and self._host.urgent_reply:
            self._host.state.note_agent_reply(self._host.urgent_reply)
            return TurnResult(tid, URGENT, text=self._host.urgent_reply, needs_model=False, frame=frame,
                              verdict=verdict, reason="urgent script")
        if verdict.route in (TOOLS, PERSONAL) and self._host.on_tools is not None:
            try:
                answered = self._host.on_tools(text, frame)
            except Exception:  # noqa: BLE001 - a failing tool means the model answers
                answered = None
            if answered:
                self._host.counts["tools_answered"] += 1
                self._host.state.note_agent_reply(_masked(answered))
                return TurnResult(tid, verdict.route, text=answered, needs_model=False, frame=frame,
                                  verdict=verdict, reason="answered by the business's tools")
        event = {"type": "turn", "turn_id": tid, "route": verdict.route, "reasons": list(verdict.reasons),
                 "shared": verdict.shared, "urgent": frame.urgent, "kind": frame.kind,
                 "confidence": frame.confidence, "question": verdict.question, "key": verdict.key,
                 "question_type": frame.question_type if verdict.shared else None}
        if verdict.route != SHARED:
            self._host.emit(dict(event, hit=False))
            return self._open_turn(TurnResult(tid, verdict.route, frame=frame, verdict=verdict,
                                              reason=";".join(verdict.reasons)))

        if self._host.replay is not None:
            self._host.replay.remember(text, verdict.question, frame.question_type)
        hit = self._lookup(verdict.key, verdict.segment)
        if hit is not None:
            self._host.counts["hits"] += 1
            result = TurnResult(tid, SHARED, text=hit, needs_model=False, frame=frame, verdict=verdict,
                                reason="cache hit")
            self._host.state.note_agent_reply(hit)
            self._host.emit(dict(event, hit=True))
            return self._open_turn(result)
        self._host.emit(dict(event, hit=False))
        messages = [{"role": "user", "content": verdict.question}]
        notes = []
        if verdict.attributes:
            notes.append("Answer for: " + "; ".join(f"{k}: {v}" for k, v in sorted(verdict.attributes.items())) + ".")
        language = self._host.state.language or frame.language
        if language:
            notes.append(f"Reply in this language: {language}.")
        if notes:
            messages.insert(0, {"role": "system", "content": " ".join(notes)})
        return self._open_turn(TurnResult(tid, SHARED, frame=frame, verdict=verdict, messages=messages,
                                          reason="cache miss"))

    def record(self, result: TurnResult, answer: str, mentions: tuple, task: Optional[str],
               private: bool = False) -> str:
        """The agent answered ``result``. Saves it when allowed and updates the call state.

        ``mentions`` are the places/products/options the agent named; ``task`` is set when
        the agent starts collecting details for a booking, order or account change.
        ``private``: the app built the answer from a tool's result, so it is never shared.
        Returns what happened: saved | slow_write | not_shared | refused:<why> | cancelled | stale.
        """
        if result.turn_id in self._cancelled:
            self._host.counts["cancelled"] += 1
            return "cancelled"
        if self._open is None or self._open.turn_id != result.turn_id:
            return "stale"  # an older turn finishing after a newer one started: never saved
        self._open = None
        kept = answer if result.route == SHARED else _masked(answer)
        self._host.state.note_agent_reply(kept, mentions, task)
        if result.route != SHARED or result.text is not None or result.verdict is None:
            return "not_shared"
        why = self.save_check(answer, result.verdict, result.frame, private=private)
        if why:
            self._host.counts["save_refused"] += 1
            return "refused:" + why
        try:
            slow = self._write(result.verdict, answer)
        except Exception:  # noqa: BLE001 - a refused write must not end a call
            self._host.counts["save_refused"] += 1
            return "refused:write_failed"
        if slow is not None:
            return slow.outcome
        self._host.counts["saved"] += 1
        self._question_records.keep(result.verdict.key, answer, result.verdict.ttl)
        return "saved"

    def cancel(self) -> bool:
        """Barge-in: the open turn is abandoned and its answer will never be saved."""
        if self._open is None:
            return False
        self._cancelled.add(self._open.turn_id)
        self._open = None
        return True

    def save_check(self, answer: str, verdict: Verdict, frame: Optional[TurnFrame] = None,
                   private: bool = False) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        chat_answer = ChatAnswer(" ".join((answer or "").split()), verdict, frame, self._host.state,
                                 instructions=self._host.instructions, prompt_key=self._host.prompt_key(),
                                 private=private)
        objection = self._save_rules.first_objection(chat_answer)
        return None if objection is None else objection.reason

    def _write(self, verdict: Verdict, answer: str):
        """agent.learn(), waited for no longer than twice the latency budget (BoundedWriter, as voice);
        without a budget it is waited for. None when written; else the BoundedWrite verdict."""
        learn = self._host.agent.learn
        if self._host.latency_budget_ms is None:
            learn(verdict.key, answer, ttl=verdict.ttl, segment=verdict.segment)
            return None
        return self._writer.write(learn, verdict.key, answer, ttl=verdict.ttl, segment=verdict.segment,
                                  deadline_s=2 * self._host.latency_budget_ms / 1000)

    def _open_turn(self, result: TurnResult) -> TurnResult:
        self._open = result
        return result

    def _understand(self, text: str) -> TurnFrame:
        """The model's frame within the budget; otherwise the safe fallback's, or an uncertain one."""
        if self._host.mode == "replay_only":
            if self._host.replay is None:
                return TurnFrame.from_dict(None)
            self._host.counts["fallback_used"] += 1
            return self._host.replay.understand(text, self._host.state)
        try:
            if self._host.understand_budget_ms is None:
                return self._host.understander.understand(text, self._host.state)
            # The worker gets its own copy of the state: a late model must never see (or race
            # with) the state of a later turn. Its late answer is simply discarded.
            state = copy.deepcopy(self._host.state)
            return _UNDERSTAND.submit(self._host.understander.understand, text, state).result(
                timeout=self._host.understand_budget_ms / 1000.0)
        except concurrent.futures.TimeoutError:
            self._host.counts["understand_timeouts"] += 1
        except Exception:  # noqa: BLE001 - understanding failing must never end a call
            self._host.counts["understand_errors"] += 1
        if self._host.replay is not None and self._host.replay is not self._host.understander:
            self._host.counts["fallback_used"] += 1
            try:
                return self._host.replay.understand(text, self._host.state)
            except Exception:  # noqa: BLE001
                pass
        return TurnFrame.from_dict(None)

    def _lookup(self, key: str, segment: Optional[str]) -> Optional[str]:
        ask = lambda: self._host.agent.ask(key, serve_above=self._host.serve_above,  # noqa: E731
                                     cheap_above=min(0.6, self._host.serve_above), segment=segment)
        started = time.monotonic()
        hit, verdict = self._cache_lookup.find(ask, started, self._host.latency_budget_ms)
        if verdict is not None:
            self._host.counts[_LOOKUP_COUNTS[verdict.rule]] += 1
            return None
        if hit.get("route") != "cache" or not hit.get("answer"):
            return None
        call = ChatHitCall(self._question_records, self._host.latency_budget_ms)
        objection = self._hit_rules.first_objection(ChatCachedAnswer(ChatHitTurn(key, call), Hit.from_agent(hit), started))
        if objection is not None:
            # A refused hit is counted by the rule that refused it (v4 hit guards).
            self._host.counts[objection.rule] = self._host.counts.get(objection.rule, 0) + 1
            return None
        return hit["answer"]
