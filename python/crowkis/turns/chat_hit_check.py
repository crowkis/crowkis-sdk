"""ChatHitCheck: stage 2 for a chat turn, as TurnCore's HitCheck."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from ..rules.chain import RuleChain
from ..runtime.question_records import QuestionRecords
from .cached_answer import CachedAnswer
from .checked import Checked
from .hit import CACHE_ROUTE, Hit
from .verdict import Verdict

# A miss, or a hit below the bar: the model answers; not counted.
NOT_CONFIDENT = Verdict("NotConfident", "no confident cached answer")
# Chat speaks a cached commitment (a price, a refund, a policy) only for the exact same question (decision V2).
CHAT_COMMITMENTS = "exact"


class ChatSessionBudget(Protocol):
    """What ChatHitCheck reads of the chat, live."""

    latency_budget_ms: Optional[float]


class ChatHitCall:
    """Adapter: the call a chat hit belongs to, as the hit rules read it (voice's VoiceCall, hit side)."""

    commitments = CHAT_COMMITMENTS

    def __init__(self, records: QuestionRecords, budget_ms: Optional[float]) -> None:
        self._records = records
        self._budget_ms = budget_ms

    def answers_another_question(self, asked: str, answer: str, spent_ms: float) -> bool:
        """Every question the cached answer was saved for asks about something else (read within
        what the lookup left of the budget)."""
        left = None if self._budget_ms is None else self._budget_ms - spent_ms
        return self._records.answers_another_question(asked, answer, left)


class ChatHitTurn:
    """The shared question a chat hit answers, as the hit rules read the turn: never personal (only a
    shared question is looked up)."""

    is_personal = False

    def __init__(self, key: str, call: ChatHitCall) -> None:
        self.key = key
        self.call = call


class ChatHitCheck:
    """A confident hit with an answer is checked by the hit rules (``hit_rules``, reading the
    questions each answer was saved for within what the lookup left of the budget); a refusal is
    counted under the rule's name. Not voice's check (``RuleSet.check_hit``): a chat stops an
    unconfident hit before its rules and uncounted, and counts a refusal by the rule's name."""

    def __init__(self, session: ChatSessionBudget, *, hit_rules: RuleChain, question_records: QuestionRecords) -> None:
        self._session = session
        self._hit_rules = hit_rules
        self._question_records = question_records

    def check_hit(self, turn: Any, hit: Dict[str, Any], started: float) -> Checked:
        if hit.get("route") != CACHE_ROUTE or not hit.get("answer"):
            return Checked(None, NOT_CONFIDENT)
        call = ChatHitCall(self._question_records, self._session.latency_budget_ms)
        cached = CachedAnswer(ChatHitTurn(turn.key, call), Hit.from_agent(hit), started)
        objection = self._hit_rules.first_objection(cached)
        if objection is None:
            return Checked(cached)
        return Checked(cached, Verdict(objection.rule, objection.reason, (objection.rule,)))
