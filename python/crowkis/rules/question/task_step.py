"""The TaskStep rule (stage 1, question; Chat, V9)."""

from __future__ import annotations

from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.routes import TASK
from ...turns.verdict import Verdict


class TaskStep:
    """A step of a task in progress (booking, ordering, a reply to the agent's own question during
    one) goes to the agent and is never shared."""

    name = "TaskStep"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (turn.frame.task_step or self._answers_agent_during_task(turn)):
            return None
        return Verdict(self.name, "V9_task_step", route=TASK)

    @staticmethod
    def _answers_agent_during_task(turn: ChatTurn) -> bool:
        """While a task is running, a reply to the agent's own question is a step of it."""
        state = turn.state
        return state.task != "none" and state.last_reply.rstrip().endswith("?") and "?" not in (turn.text or "")
