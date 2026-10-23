"""ChatAnswer: the model's answer to a shared Chat question, as Chat's save rules read it."""

from __future__ import annotations

from typing import Any, Optional, Tuple

from ..state.call_state import CallState
from ..understanding.turn_frame import TurnFrame


class ChatAnswer:
    """The answer (``text``: its words, spaces normalised), the shared question's verdict (its
    question and the attributes in its key), the frame of the turn, the chat's state, and the
    system prompt the model read with ``prompt_key`` naming whose prompts it is compared with."""

    def __init__(self, text: str, verdict: Any, frame: Optional[TurnFrame], state: CallState, *,
                 instructions: str, prompt_key: Tuple, private: bool = False) -> None:
        self.text = text
        # The app built this answer from a tool's result (ChatToolResult keeps it in the chat).
        self.private = private
        self.verdict = verdict
        self.frame = frame
        self.state = state
        self.instructions = instructions
        self.prompt_key = prompt_key
