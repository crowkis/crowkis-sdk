"""ChatTurn: one Chat turn, as Chat's question rules read it."""

from __future__ import annotations

from ..state.call_state import CallState
from ..understanding.turn_frame import TurnFrame


class ChatTurn:
    """A user's turn in a chat (``text``), the understanding model's frame of it, and the chat's
    state so far. ``question`` is the frame's stand-alone question (None when it gave none)."""

    def __init__(self, frame: TurnFrame, text: str, state: CallState) -> None:
        self.frame = frame
        self.text = text
        self.state = state

    @property
    def question(self):
        return self.frame.question
