"""The TaskStep rule (stage 1, question; Chat, V9)."""

from __future__ import annotations

import re
from typing import Optional

from ...turns.chat_turn import ChatTurn
from ...turns.routes import TASK
from ...turns.verdict import Verdict


# A clock time ("8:45 PM", "9 am", "21:30"): while a task runs it is one of the task's own details.
CLOCK_TIME = re.compile(r"\b\d{1,2}(:\d{2})\s*(am|pm|a\.m\.|p\.m\.)?\b|\b\d{1,2}\s*(am|pm|a\.m\.|p\.m\.)(?!\w)", re.I)


class TaskStep:
    """A step of a task in progress (booking, ordering, a reply to the agent's own question during
    one) goes to the agent and is never shared."""

    name = "TaskStep"
    floor = False

    def check(self, turn: ChatTurn) -> Optional[Verdict]:
        if not (turn.frame.task_step or self._answers_agent_during_task(turn) or self._names_a_time_during_task(turn)):
            return None
        return Verdict(self.name, "V9_task_step", route=TASK)

    @staticmethod
    def _names_a_time_during_task(turn: ChatTurn) -> bool:
        """While a task runs, a question naming a clock time is about the task ("Does the 8:45 PM flight
        have a meal?" while a flight is being changed: v4, misfire C01), never a general question."""
        return turn.state.task != "none" and bool(CLOCK_TIME.search(turn.text or ""))

    @staticmethod
    def _answers_agent_during_task(turn: ChatTurn) -> bool:
        """While a task is running, a reply to the agent's own question is a step of it."""
        state = turn.state
        return state.task != "none" and state.last_reply.rstrip().endswith("?") and "?" not in (turn.text or "")
