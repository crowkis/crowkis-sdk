"""ChatSaving: the save check and the write of a chat's answers, as TurnCore's Saving."""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, Tuple

from ..rules.chain import RuleChain
from ..runtime.bounded_writer import BoundedWriter
from ..runtime.question_records import QuestionRecords
from ..state.call_state import CallState
from ..understanding.chat_details import _masked
from ..understanding.turn_frame import TurnFrame
from .answered import ChatAnswered
from .chat_answer import ChatAnswer
from .checked import Checked
from .outcome import Outcome
from .routes import SHARED
from .verdict import Verdict

SAVED_COUNT = "saved"
NOT_SHARED = Verdict("NotShared", "not a shared question the model answered", outcome=Outcome.NOT_SHARED)
SAVE_REFUSED = "save_refused"


class ChatSessionSaves(Protocol):
    """What ChatSaving reads of the chat, live."""

    state: CallState
    counts: Dict[str, int]
    agent: Any
    instructions: str
    latency_budget_ms: Optional[float]

    def prompt_key(self) -> Tuple:
        """Whose system prompts this chat's is compared with."""


class ChatSaving:
    """check(): the agent's reply is noted in the chat's state (names masked unless the question was
    shared); only the model's answer to a shared question may be saved, and only past the save rules.
    write(): ``agent.learn()``, waited for no longer than twice the latency budget (``BoundedWriter``,
    as voice; waited for without a budget), then the question it was saved for is kept."""

    def __init__(self, session: ChatSessionSaves, *, save_rules: RuleChain, writer: BoundedWriter,
                 question_records: QuestionRecords) -> None:
        self._session = session
        self._save_rules = save_rules
        self._writer = writer
        self._question_records = question_records

    def check(self, answered: ChatAnswered) -> Checked:
        result, answer = answered.result, answered.answer
        kept = answer if result.route == SHARED else _masked(answer)
        self._session.state.note_agent_reply(kept, answered.mentions, answered.task)
        if result.route != SHARED or result.text is not None or result.verdict is None:
            return Checked(answered, NOT_SHARED)
        why = self.save_check(answer, result.verdict, result.frame, private=answered.private)
        if why:
            return Checked(answered, Verdict("SaveCheck", why, (SAVE_REFUSED,), outcome=Outcome.REFUSED.because(why)))
        return Checked(answered)

    def write(self, answered: ChatAnswered) -> str:
        verdict, answer = answered.result.verdict, answered.answer
        written = self._writer.write_within(self._session.agent.learn, verdict.key, answer, ttl=verdict.ttl,
                                            segment=verdict.segment, budget_ms=self._session.latency_budget_ms)
        if not written.written:
            return str(written.objection.outcome)
        self._session.counts[SAVED_COUNT] += 1
        self._question_records.keep(verdict.key, answer, verdict.ttl)
        return str(Outcome.SAVED)

    def save_check(self, answer: str, verdict: Any, frame: Optional[TurnFrame] = None,
                   private: bool = False) -> Optional[str]:
        """Why an answer to a shared question must not be saved, or None."""
        chat_answer = ChatAnswer(" ".join((answer or "").split()), verdict, frame, self._session.state,
                                 instructions=self._session.instructions, prompt_key=self._session.prompt_key(),
                                 private=private)
        objection = self._save_rules.first_objection(chat_answer)
        return None if objection is None else objection.reason
