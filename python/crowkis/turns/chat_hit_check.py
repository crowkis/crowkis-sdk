"""ChatHitCheck: stage 2 for a chat turn, as TurnCore's HitCheck."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from ..rules.chain import RuleChain
from ..runtime.question_records import QuestionRecords
from .chat_cached_answer import ChatCachedAnswer, ChatHitCall, ChatHitTurn
from .checked import Checked
from .hit import CACHE_ROUTE, Hit
from .verdict import Verdict

# A miss, or a hit below the bar: the model answers; not counted.
NOT_CONFIDENT = Verdict("NotConfident", "no confident cached answer")


class ChatSessionBudget(Protocol):
    """What ChatHitCheck reads of the chat, live."""

    latency_budget_ms: Optional[float]


class ChatHitCheck:
    """A confident hit with an answer is checked by the hit rules (``hit_rules``, reading the
    questions each answer was saved for within what the lookup left of the budget); a refusal is
    counted under the rule's name."""

    def __init__(self, session: ChatSessionBudget, *, hit_rules: RuleChain, question_records: QuestionRecords) -> None:
        self._session = session
        self._hit_rules = hit_rules
        self._question_records = question_records

    def check_hit(self, turn: Any, hit: Dict[str, Any], started: float) -> Checked:
        if hit.get("route") != CACHE_ROUTE or not hit.get("answer"):
            return Checked(None, NOT_CONFIDENT)
        call = ChatHitCall(self._question_records, self._session.latency_budget_ms)
        cached = ChatCachedAnswer(ChatHitTurn(turn.key, call), Hit.from_agent(hit), started)
        objection = self._hit_rules.first_objection(cached)
        if objection is None:
            return Checked(cached)
        return Checked(cached, Verdict(objection.rule, objection.reason, (objection.rule,)))
