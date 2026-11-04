"""Chat's question check and hit check, the twin of rules/rule_set.py's voice checks."""

from __future__ import annotations

from typing import Any, Dict, Optional, TYPE_CHECKING

from ...rules.chain import RuleChain
from ...rules.question import UrgentWords
from ...rules.rule_checker import Verdict as ChatVerdict
from ...runtime.question_records import QuestionRecords
from ...state.call_state import CallState
from ...understanding.chat_details import _private_words
from ..results import AGENT, URGENT
from ..values import CACHE_ROUTE, CachedAnswer, Checked, Hit, Verdict
from .turn import ChatReading, ChatTurn

if TYPE_CHECKING:
    from ...channels.call_session import CallSession

CHECK_RULE = "ChatQuestionCheck"


class ChatQuestionCheck:
    """The rule checker (V1-V10, every objection reported) keys a shareable question; then, on what
    the chat has learnt, the shared-question rules may still keep it with the agent, and the fixed
    urgent words send a turn about the user to the urgent route whatever the model said. The chat's
    state takes the turn in, and its route is counted. A shared question is remembered by the safe
    fallback; any other route is the objection (the model answers with the whole chat)."""

    def __init__(self, session: CallSession, *, shared_question_rules: RuleChain,
                 urgent_words: UrgentWords) -> None:
        self._session = session
        self._shared_question_rules = shared_question_rules
        self._urgent_words = urgent_words

    def check_question(self, reading: ChatReading) -> Checked:
        verdict = self._verdict(reading)
        state = self._session.state
        state.apply(reading.frame, shared=verdict.shared)
        state.note_private((_private_words(reading.text, reading.frame) if not verdict.shared else []) + reading.names)
        self._session.counts[verdict.route] += 1
        checked = reading.checked_as(verdict)
        if not verdict.shared:
            return Checked(checked, Verdict(CHECK_RULE, ";".join(verdict.reasons), route=verdict.route))
        if self._session.replay is not None:
            self._session.replay.remember(reading.text, verdict.question, reading.frame.question_type)
        return Checked(checked)

    def _verdict(self, reading: ChatReading) -> ChatVerdict:
        verdict = self._session.checker.check(reading.frame, reading.text, self._session.state)
        chat_turn = ChatTurn(reading.frame, reading.text, self._session.state)
        if verdict.shared:
            objection = self._shared_question_rules.first_objection(chat_turn)
            if objection is not None:
                verdict = ChatVerdict(False, AGENT, [objection.reason])
        if verdict.route != URGENT and reading.about_caller:
            objection = self._urgent_words.check(chat_turn)
            if objection is not None:
                verdict = ChatVerdict(False, objection.route, [objection.reason])  # never left to the model alone
        return verdict


# A miss, or a hit below the bar: the model answers; not counted.
NOT_CONFIDENT = Verdict("NotConfident", "no confident cached answer")
# Chat speaks a cached commitment (a price, a refund, a policy) only for the exact same question (decision V2).
CHAT_COMMITMENTS = "exact"


class ChatHitCall:
    """Adapter: the call a chat hit belongs to, as the hit rules read it (the SessionCall of voice, hit side)."""

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

    def __init__(self, session: CallSession, *, hit_rules: RuleChain, question_records: QuestionRecords) -> None:
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
