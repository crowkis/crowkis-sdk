"""ChatQuestionCheck: stage 1 for a chat turn, as TurnCore's QuestionCheck."""

from __future__ import annotations

from typing import Any, Dict, Protocol

from ..rules.chain import RuleChain
from ..rules.question import UrgentWords
from ..rules.rule_checker import Verdict as ChatVerdict
from ..state.call_state import CallState
from ..understanding.chat_details import _private_words
from .chat_reading import ChatReading
from .chat_turn import ChatTurn
from .checked import Checked
from .routes import AGENT, URGENT
from .verdict import Verdict

CHECK_RULE = "ChatQuestionCheck"


class ChatSessionChecks(Protocol):
    """What ChatQuestionCheck reads of the chat, live."""

    state: CallState
    counts: Dict[str, int]
    checker: Any
    replay: Any


class ChatQuestionCheck:
    """The rule checker (V1-V10, every objection reported) keys a shareable question; then, on what
    the chat has learnt, the shared-question rules may still keep it with the agent, and the fixed
    urgent words send a turn about the user to the urgent route whatever the model said. The chat's
    state takes the turn in, and its route is counted. A shared question is remembered by the safe
    fallback; any other route is the objection (the model answers with the whole chat)."""

    def __init__(self, session: ChatSessionChecks, *, shared_question_rules: RuleChain,
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
